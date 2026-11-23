from __future__ import annotations

import csv
import multiprocessing
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from PIL import Image
from Pyro5.api import Proxy
from Pyro5.errors import CommunicationError
from serpent import tobytes

from parallel_ocr_pipeline import distributed
from parallel_ocr_pipeline.distributed import (
    INITIAL_CONNECT_ATTEMPTS,
    MASTER_OBJECT_ID,
    MAX_IMAGE_BYTES,
    RPC_ATTEMPTS,
    _run_worker_process,
    run_worker,
)
from parallel_ocr_pipeline.distributed_config import WorkerConfig

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MASTER_SCRIPT = REPOSITORY_ROOT / "scripts" / "run_master.py"


class FixedTextRecognizer:
    """Return marker-specific text so the network test can check image association."""

    def recognize(self, image: Image.Image, /) -> str:
        marker = image.getpixel((0, 0))
        if marker == (17, 0, 0):
            return 'first, "quoted" line\nsecond line'
        assert marker == (23, 0, 0)
        return "second image result"


class ProcessIdRecognizer:
    def recognize(self, image: Image.Image, /) -> str:
        time.sleep(0.1)
        return str(os.getpid())


class MarkerThenWaitRecognizer:
    def __init__(self, marker_path: str) -> None:
        self._marker_path = Path(marker_path)

    def recognize(self, image: Image.Image, /) -> str:
        self._marker_path.write_text(str(os.getpid()), encoding="utf-8")
        time.sleep(30)
        return "late result"


class ScriptedMasterProxy:
    """Replay scripted get_work outcomes; once exhausted, the master never answers."""

    def __init__(self, outcomes: list[dict[str, Any] | Exception]) -> None:
        self._outcomes = list(outcomes)
        self.get_work_calls = 0

    def get_work(self, *args: object) -> dict[str, Any]:
        self.get_work_calls += 1
        outcome = self._outcomes.pop(0) if self._outcomes else CommunicationError("master is down")
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def _pyroRelease(self) -> None:
        pass


def _worker_child(config_path: str) -> None:
    raise SystemExit(run_worker(config_path, recognizer_factory=FixedTextRecognizer))


def _worker_node_with_process_ids(config_path: str) -> None:
    raise SystemExit(run_worker(config_path, recognizer_factory=ProcessIdRecognizer))


def _stoppable_worker_node(config_path: str, marker_path: str) -> None:
    raise SystemExit(
        run_worker(config_path, recognizer_factory=partial(MarkerThenWaitRecognizer, marker_path))
    )


def _free_port() -> int:
    with socket.socket() as connection:
        connection.bind(("127.0.0.1", 0))
        return int(connection.getsockname()[1])


def _write_image(path: Path, marker: int = 17) -> None:
    image = Image.new("RGB", (3, 3), (marker, 0, 0))
    image.save(path)
    image.close()


def _rpc(proxy: Proxy, method: str, *args: object) -> dict[str, Any]:
    result = getattr(proxy, method)(*args)
    assert isinstance(result, dict)
    return result


def _start_master(tmp_path: Path, images: Path) -> tuple[subprocess.Popen[str], int, Path]:
    port = _free_port()
    config = tmp_path / "master_config.txt"
    config.write_text(f"image_dir={images}\nport={port}\n", encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, str(MASTER_SCRIPT), str(config)],
        cwd=REPOSITORY_ROOT,
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return process, port, config


def _start_fast_master(
    tmp_path: Path,
    images: Path,
    *,
    assignment_timeout: float = 0.2,
    max_reassignments: int = 2,
    shutdown_timeout: float = 0.5,
    startup_timeout: float = 5.0,
    idle_timeout: float = 2.0,
    interrupt_marker: Path | None = None,
) -> tuple[subprocess.Popen[str], int, Path]:
    port = _free_port()
    config = tmp_path / "master_config.txt"
    config.write_text(f"image_dir={images}\nport={port}\n", encoding="utf-8")
    runner = tmp_path / "fast_master.py"
    runner_source = (
        "import sys\n"
        "from pathlib import Path\n"
        "from parallel_ocr_pipeline import distributed\n"
        "distributed.Pyro5.api.config.POLLTIMEOUT = 0.05\n"
    )
    if interrupt_marker is not None:
        runner_source += f"import signal\ninterrupt_marker = Path({str(interrupt_marker)!r})\n"
    runner_source += (
        "class FastMasterCoordinator(distributed.MasterCoordinator):\n"
        "    def __init__(self, config):\n"
        "        super().__init__(\n"
        f"            config, assignment_timeout={assignment_timeout!r},\n"
        f"            max_reassignments={max_reassignments!r},\n"
        f"            shutdown_timeout={shutdown_timeout!r}, startup_timeout={startup_timeout!r},\n"
        f"            idle_timeout={idle_timeout!r}\n"
        "        )\n"
    )
    if interrupt_marker is not None:
        runner_source += (
            "        self._test_signal_raised = False\n"
            "    def should_continue(self):\n"
            "        if interrupt_marker.exists() and not self._test_signal_raised:\n"
            "            self._test_signal_raised = True\n"
            "            signal.raise_signal(signal.SIGINT)\n"
            "        return super().should_continue()\n"
        )
    runner_source += "distributed.MasterCoordinator = FastMasterCoordinator\n"
    runner_source += "raise SystemExit(distributed.run_master(Path(sys.argv[1])))\n"
    runner.write_text(runner_source, encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, str(runner), str(config)],
        cwd=REPOSITORY_ROOT,
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return process, port, config


def _wait_for_server(process: subprocess.Popen[str], port: int) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise AssertionError(f"master exited early ({process.returncode})\n{stdout}\n{stderr}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                return
        except OSError:
            time.sleep(0.05)
    raise TimeoutError(f"master did not listen on port {port}")


def _finish_master(process: subprocess.Popen[str]) -> tuple[int, str, str]:
    try:
        stdout, stderr = process.communicate(timeout=20)
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate()
        raise AssertionError(f"master did not shut down\n{stdout}\n{stderr}") from None
    return process.returncode or 0, stdout, stderr


def _write_worker_config(tmp_path: Path, port: int) -> Path:
    config = tmp_path / "worker_config.txt"
    config.write_text(
        f"master_host=127.0.0.1\nmaster_port={port}\nn_workers=1\n",
        encoding="utf-8",
    )
    return config


def test_worker_process_receives_image_over_pyro_recognizes_and_writes_csv(
    tmp_path: Path,
) -> None:
    images = tmp_path / "images"
    images.mkdir()
    _write_image(images / "one.png")
    _write_image(images / "two.png", marker=23)
    (tmp_path / "ocr_results.csv").write_text("previous complete output\n", encoding="utf-8")
    master, port, _ = _start_master(tmp_path, images)
    context = multiprocessing.get_context("spawn")
    worker = context.Process(
        target=_worker_child, args=(str(_write_worker_config(tmp_path, port)),)
    )

    try:
        _wait_for_server(master, port)
        worker.start()
        worker.join(timeout=20)
        if worker.is_alive():
            worker.terminate()
            worker.join(timeout=5)
            raise AssertionError("worker process did not terminate")
        assert worker.exitcode == 0
        status, stdout, stderr = _finish_master(master)
    finally:
        if worker.is_alive():
            worker.terminate()
            worker.join(timeout=5)
        if master.poll() is None:
            master.kill()
            master.communicate()

    assert status == 0, stderr
    assert "Completed 2 image" in stdout
    with (tmp_path / "ocr_results.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 2
    assert rows[0]["image_id"] == "1"
    assert rows[0]["filename"] == "one.png"
    assert rows[0]["text"] == 'first, "quoted" line\nsecond line'
    assert rows[1]["image_id"] == "2"
    assert rows[1]["filename"] == "two.png"
    assert rows[1]["text"] == "second image result"
    assert all(float(row["processing_time_ms"]) >= 0 for row in rows)
    assert not (tmp_path / "ocr_results.partial.csv").exists()
    assert not (tmp_path / "ocr_failures.csv").exists()
    assert not (tmp_path / "ocr_results.previous.csv").exists()


def test_worker_node_runs_multiple_spawned_processes(tmp_path: Path) -> None:
    images = tmp_path / "images"
    images.mkdir()
    for index in range(12):
        _write_image(images / f"{index:02}.png")
    master, port, _ = _start_master(tmp_path, images)
    config = _write_worker_config(tmp_path, port)
    config.write_text(f"master_host=127.0.0.1\nmaster_port={port}\nn_workers=3\n", encoding="utf-8")
    worker = multiprocessing.get_context("spawn").Process(
        target=_worker_node_with_process_ids, args=(str(config),)
    )
    try:
        _wait_for_server(master, port)
        worker.start()
        worker.join(timeout=30)
        assert not worker.is_alive(), "worker node did not terminate"
        assert worker.exitcode == 0
        status, _, stderr = _finish_master(master)
        assert status == 0, stderr
        with (tmp_path / "ocr_results.csv").open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        assert len(rows) == 12
        assert len({row["filename"] for row in rows}) == 12
        assert len({row["text"] for row in rows}) == 3
    finally:
        if worker.is_alive():
            worker.terminate()
            worker.join(timeout=5)
        if master.poll() is None:
            master.kill()
            master.communicate()


def test_two_worker_nodes_process_a_shared_workload(tmp_path: Path) -> None:
    images = tmp_path / "images"
    images.mkdir()
    for index in range(20):
        _write_image(images / f"{index:02}.png")
    master, port, _ = _start_master(tmp_path, images)
    config = _write_worker_config(tmp_path, port)
    context = multiprocessing.get_context("spawn")
    workers = [
        context.Process(target=_worker_node_with_process_ids, args=(str(config),)) for _ in range(2)
    ]
    started = []
    try:
        _wait_for_server(master, port)
        for worker in workers:
            worker.start()
            started.append(worker)
        for worker in workers:
            worker.join(timeout=30)
            assert not worker.is_alive(), "worker node did not terminate"
            assert worker.exitcode == 0
        status, _, stderr = _finish_master(master)
        assert status == 0, stderr
        with (tmp_path / "ocr_results.csv").open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        assert len(rows) == 20
        assert len({row["filename"] for row in rows}) == 20
        assert len({row["text"] for row in rows}) == 2
    finally:
        for worker in started:
            if worker.is_alive():
                worker.terminate()
                worker.join(timeout=5)
        if master.poll() is None:
            master.kill()
            master.communicate()


def test_pyro_work_request_replays_same_image_and_result_ack_is_idempotent(
    tmp_path: Path,
) -> None:
    images = tmp_path / "images"
    images.mkdir()
    image_path = images / "one.png"
    _write_image(image_path)
    _write_image(images / "two.png", marker=23)
    master, port, _ = _start_master(tmp_path, images)
    uri = f"PYRO:{MASTER_OBJECT_ID}@127.0.0.1:{port}"
    proxy = Proxy(uri)
    proxy._pyroTimeout = 5

    try:
        _wait_for_server(master, port)
        malformed = _rpc(proxy, "get_work", "", "process", "request")
        assert malformed["status"] == "rejected"

        invalid_outcome = _rpc(
            proxy,
            "submit_result",
            "node",
            "process",
            "request",
            "token",
            ["not", "a", "result"],
        )
        assert invalid_outcome["status"] == "rejected"
        huge_processing_time = _rpc(
            proxy,
            "submit_result",
            "node",
            "process",
            "request",
            "token",
            {
                "status": "success",
                "text": "invalid",
                "processing_time_ms": 10**400,
            },
        )
        assert huge_processing_time["status"] == "rejected"

        first = _rpc(proxy, "get_work", "node", "process", "request")
        replay = _rpc(proxy, "get_work", "node", "process", "request")
        assert first["status"] == "work"
        assert replay["status"] == "work"
        assert replay["attempt_token"] == first["attempt_token"]
        assert tobytes(first["image_bytes"]) == image_path.read_bytes()
        other_node_first = _rpc(proxy, "get_work", "other-node", "process", "request")
        assert other_node_first["status"] == "work"
        assert other_node_first["attempt_token"] != first["attempt_token"]
        assert other_node_first["image_id"] != first["image_id"]
        assert _rpc(proxy, "get_work", "node", "process", "parallel") == {"status": "wait"}

        outcome = {
            "status": "success",
            "text": "recognized",
            "processing_time_ms": 1.25,
        }
        wrong_node = _rpc(
            proxy,
            "submit_result",
            "other-node",
            "process",
            first["request_id"],
            first["attempt_token"],
            outcome,
        )
        wrong_token = _rpc(
            proxy,
            "submit_result",
            "node",
            "process",
            first["request_id"],
            "wrong-token",
            outcome,
        )
        assert wrong_node["status"] == "rejected"
        assert wrong_token["status"] == "rejected"

        accepted = _rpc(
            proxy,
            "submit_result",
            "node",
            "process",
            first["request_id"],
            first["attempt_token"],
            outcome,
        )
        duplicate = _rpc(
            proxy,
            "submit_result",
            "node",
            "process",
            first["request_id"],
            first["attempt_token"],
            outcome,
        )
        assert accepted == {"status": "accepted", "duplicate": False}
        assert duplicate == {"status": "accepted", "duplicate": True}
        cross_node_duplicate = _rpc(
            proxy,
            "submit_result",
            "other-node",
            "process",
            first["request_id"],
            first["attempt_token"],
            outcome,
        )
        assert cross_node_duplicate["status"] == "rejected"

        other_outcome = {
            "status": "success",
            "text": "second recognized",
            "processing_time_ms": 2.5,
        }
        other_accepted = _rpc(
            proxy,
            "submit_result",
            "other-node",
            "process",
            other_node_first["request_id"],
            other_node_first["attempt_token"],
            other_outcome,
        )
        assert other_accepted == {"status": "accepted", "duplicate": False}
        other_duplicate = _rpc(
            proxy,
            "submit_result",
            "other-node",
            "process",
            other_node_first["request_id"],
            other_node_first["attempt_token"],
            other_outcome,
        )
        assert other_duplicate == {"status": "accepted", "duplicate": True}
        completed = _rpc(proxy, "get_work", "node", "process", first["request_id"])
        other_completed = _rpc(
            proxy, "get_work", "other-node", "process", other_node_first["request_id"]
        )
        shutdown = _rpc(proxy, "get_work", "node", "process", "next")
        other_shutdown = _rpc(proxy, "get_work", "other-node", "process", "next")
        assert completed["status"] == "completed"
        assert other_completed["status"] == "completed"
        assert other_shutdown == {"status": "shutdown"}
        assert shutdown["status"] == "shutdown"
        status, _, stderr = _finish_master(master)
    finally:
        proxy._pyroRelease()
        if master.poll() is None:
            master.kill()
            master.communicate()

    assert status == 0, stderr
    with (tmp_path / "ocr_results.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert [(row["image_id"], row["filename"], row["text"]) for row in rows] == [
        ("1", "one.png", "recognized"),
        ("2", "two.png", "second recognized"),
    ]


def test_expired_assignment_is_reassigned_and_old_request_and_result_are_rejected(
    tmp_path: Path,
) -> None:
    images = tmp_path / "images"
    images.mkdir()
    _write_image(images / "one.png")
    master, port, _ = _start_fast_master(tmp_path, images)
    proxy = Proxy(f"PYRO:{MASTER_OBJECT_ID}@127.0.0.1:{port}")
    proxy._pyroTimeout = 5

    try:
        _wait_for_server(master, port)
        original = _rpc(proxy, "get_work", "stopped-node", "process-1", "request-1")
        assert original["status"] == "work"

        time.sleep(0.3)
        replay = _rpc(proxy, "get_work", "stopped-node", "process-1", "request-1")
        assert replay["status"] == "rejected"

        reassigned = _rpc(proxy, "get_work", "live-node", "process-2", "request-2")
        assert reassigned["status"] == "work"
        assert reassigned["image_id"] == original["image_id"]
        assert reassigned["attempt_token"] != original["attempt_token"]

        stale_result = _rpc(
            proxy,
            "submit_result",
            "stopped-node",
            "process-1",
            "request-1",
            original["attempt_token"],
            {"status": "success", "text": "stale", "processing_time_ms": 1.0},
        )
        assert stale_result["status"] == "rejected"

        accepted = _rpc(
            proxy,
            "submit_result",
            "live-node",
            "process-2",
            "request-2",
            reassigned["attempt_token"],
            {"status": "success", "text": "recovered", "processing_time_ms": 2.0},
        )
        assert accepted == {"status": "accepted", "duplicate": False}
        shutdown = _rpc(proxy, "get_work", "live-node", "process-2", "request-3")
        assert shutdown == {"status": "shutdown"}
        status, _, stderr = _finish_master(master)
    finally:
        proxy._pyroRelease()
        if master.poll() is None:
            master.kill()
            master.communicate()

    assert status == 0, stderr
    with (tmp_path / "ocr_results.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert [(row["image_id"], row["filename"], row["text"]) for row in rows] == [
        ("1", "one.png", "recovered")
    ]


def test_stopped_worker_process_is_reassigned_to_a_live_worker(tmp_path: Path) -> None:
    images = tmp_path / "images"
    images.mkdir()
    _write_image(images / "one.png")
    master, port, _ = _start_fast_master(
        tmp_path, images, assignment_timeout=0.8, shutdown_timeout=5.0
    )
    config = _write_worker_config(tmp_path, port)
    marker = tmp_path / "recognition-started"
    context = multiprocessing.get_context("spawn")
    stopped_worker = context.Process(target=_stoppable_worker_node, args=(str(config), str(marker)))
    live_worker = context.Process(target=_worker_child, args=(str(config),))

    try:
        _wait_for_server(master, port)
        stopped_worker.start()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not marker.exists():
            if stopped_worker.exitcode is not None:
                raise AssertionError(f"stoppable worker exited early: {stopped_worker.exitcode}")
            time.sleep(0.05)
        assert marker.exists(), "worker did not begin recognizing its assigned image"

        child_pid = int(marker.read_text(encoding="utf-8"))
        os.kill(child_pid, signal.SIGTERM)
        stopped_worker.join(timeout=20)
        assert not stopped_worker.is_alive(), "worker node did not stop after its child was stopped"
        assert stopped_worker.exitcode != 0

        live_worker.start()
        live_worker.join(timeout=20)
        assert not live_worker.is_alive(), "replacement worker did not terminate"
        assert live_worker.exitcode == 0
        status, _, stderr = _finish_master(master)
    finally:
        for worker in (stopped_worker, live_worker):
            if worker.is_alive():
                worker.terminate()
                worker.join(timeout=5)
        if master.poll() is None:
            master.kill()
            master.communicate()

    assert status == 0, stderr
    with (tmp_path / "ocr_results.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert [(row["image_id"], row["filename"], row["text"]) for row in rows] == [
        ("1", "one.png", 'first, "quoted" line\nsecond line')
    ]


def test_interrupted_master_sends_shutdown_and_writes_incomplete_output(
    tmp_path: Path,
) -> None:
    images = tmp_path / "images"
    images.mkdir()
    _write_image(images / "one.png")
    interrupt_marker = tmp_path / "interrupt-master"
    master, port, _ = _start_fast_master(
        tmp_path,
        images,
        assignment_timeout=60.0,
        idle_timeout=60.0,
        shutdown_timeout=5.0,
        interrupt_marker=interrupt_marker,
    )
    proxy = Proxy(f"PYRO:{MASTER_OBJECT_ID}@127.0.0.1:{port}")
    proxy._pyroTimeout = 5

    try:
        _wait_for_server(master, port)
        assignment = _rpc(proxy, "get_work", "node", "process", "request-1")
        assert assignment["status"] == "work"
        interrupt_marker.touch()
        shutdown = None
        deadline = time.monotonic() + 5
        request_number = 2
        while time.monotonic() < deadline:
            response = _rpc(proxy, "get_work", "node", "process", f"request-{request_number}")
            request_number += 1
            if response["status"] == "shutdown":
                shutdown = response
                break
            assert response["status"] == "wait"
            time.sleep(0.05)
        assert shutdown == {"status": "shutdown"}
        status, _, stderr = _finish_master(master)
    finally:
        proxy._pyroRelease()
        if master.poll() is None:
            master.kill()
            master.communicate()

    assert status == 1
    assert "Incomplete workload" in stderr
    assert not (tmp_path / "ocr_results.csv").exists()
    assert (tmp_path / "ocr_results.partial.csv").exists()
    with (tmp_path / "ocr_failures.csv").open(encoding="utf-8", newline="") as stream:
        failures = list(csv.DictReader(stream))
    assert [(row["image_id"], row["stage"]) for row in failures] == [("1", "incomplete")]


def test_recovery_exhaustion_preserves_partial_and_failure_artifacts(tmp_path: Path) -> None:
    images = tmp_path / "images"
    images.mkdir()
    _write_image(images / "one.png")
    prior_output = b"previous complete output\n"
    (tmp_path / "ocr_results.csv").write_bytes(prior_output)
    master, port, _ = _start_fast_master(
        tmp_path, images, assignment_timeout=0.15, max_reassignments=2
    )
    proxy = Proxy(f"PYRO:{MASTER_OBJECT_ID}@127.0.0.1:{port}")
    proxy._pyroTimeout = 5

    try:
        _wait_for_server(master, port)
        for attempt in range(3):
            node_id = f"node-{attempt}"
            process_id = f"process-{attempt}"
            request_id = f"request-{attempt}"
            assignment = _rpc(proxy, "get_work", node_id, process_id, request_id)
            assert assignment["status"] == "work"
            assert assignment["image_id"] == 1
            time.sleep(0.22)

            if attempt < 2:
                expired = _rpc(proxy, "get_work", node_id, process_id, request_id)
                assert expired["status"] == "rejected"

        shutdown = _rpc(proxy, "get_work", "observer", "process", "after-exhaustion")
        assert shutdown == {"status": "shutdown"}
        status, _, stderr = _finish_master(master)
    finally:
        proxy._pyroRelease()
        if master.poll() is None:
            master.kill()
            master.communicate()

    assert status == 1
    assert "0 succeeded, 1 failed" in stderr
    assert not (tmp_path / "ocr_results.csv").exists()
    assert (tmp_path / "ocr_results.previous.csv").read_bytes() == prior_output
    with (tmp_path / "ocr_results.partial.csv").open(encoding="utf-8", newline="") as stream:
        assert list(csv.DictReader(stream)) == []
    with (tmp_path / "ocr_failures.csv").open(encoding="utf-8", newline="") as stream:
        failures = list(csv.DictReader(stream))
    assert [(row["image_id"], row["filename"], row["stage"]) for row in failures] == [
        ("1", "one.png", "worker_recovery")
    ]
    assert failures[0]["exception_type"] == "AssignmentTimeout"


def test_wait_polling_does_not_extend_master_idle_deadline(tmp_path: Path) -> None:
    images = tmp_path / "images"
    images.mkdir()
    _write_image(images / "one.png")
    master, port, _ = _start_fast_master(
        tmp_path,
        images,
        assignment_timeout=60.0,
        idle_timeout=0.35,
        shutdown_timeout=2.0,
    )
    proxy = Proxy(f"PYRO:{MASTER_OBJECT_ID}@127.0.0.1:{port}")
    proxy._pyroTimeout = 5

    try:
        _wait_for_server(master, port)
        assignment = _rpc(proxy, "get_work", "busy-node", "busy-process", "work-request")
        assert assignment["status"] == "work"
        wait_responses = []
        shutdown = None
        deadline = time.monotonic() + 5
        request_number = 1
        while time.monotonic() < deadline:
            response = _rpc(
                proxy,
                "get_work",
                "idle-node",
                "idle-process",
                f"wait-request-{request_number}",
            )
            request_number += 1
            if response["status"] == "shutdown":
                shutdown = response
                break
            wait_responses.append(response)
            assert response["status"] == "wait"
            time.sleep(0.12)
        assert len(wait_responses) >= 2
        assert shutdown == {"status": "shutdown"}

        owner_shutdown = _rpc(proxy, "get_work", "busy-node", "busy-process", "after-idle-timeout")
        assert owner_shutdown == {"status": "shutdown"}
        status, _, stderr = _finish_master(master)
    finally:
        proxy._pyroRelease()
        if master.poll() is None:
            master.kill()
            master.communicate()

    assert status == 1
    assert "Incomplete workload" in stderr
    assert not (tmp_path / "ocr_results.csv").exists()
    assert (tmp_path / "ocr_results.partial.csv").exists()


def test_master_bounds_startup_wait_when_no_worker_connects(tmp_path: Path) -> None:
    images = tmp_path / "images"
    images.mkdir()
    _write_image(images / "one.png")
    master, _, _ = _start_fast_master(tmp_path, images, startup_timeout=0.2, shutdown_timeout=0.2)

    started = time.monotonic()
    status, _, stderr = _finish_master(master)
    elapsed = time.monotonic() - started

    assert status == 1
    assert elapsed < 5
    assert "Incomplete workload" in stderr
    assert not (tmp_path / "ocr_results.csv").exists()
    assert (tmp_path / "ocr_results.partial.csv").exists()


def test_cancelled_master_bounds_shutdown_if_worker_stays_busy(tmp_path: Path) -> None:
    images = tmp_path / "images"
    images.mkdir()
    _write_image(images / "one.png")
    interrupt_marker = tmp_path / "interrupt-master"
    master, port, _ = _start_fast_master(
        tmp_path,
        images,
        assignment_timeout=60.0,
        idle_timeout=60.0,
        shutdown_timeout=0.25,
        interrupt_marker=interrupt_marker,
    )
    proxy = Proxy(f"PYRO:{MASTER_OBJECT_ID}@127.0.0.1:{port}")
    proxy._pyroTimeout = 5

    try:
        _wait_for_server(master, port)
        assignment = _rpc(proxy, "get_work", "busy-node", "busy-process", "work-request")
        assert assignment["status"] == "work"
        interrupt_marker.touch()
        started = time.monotonic()
        status, _, stderr = _finish_master(master)
        elapsed = time.monotonic() - started
    finally:
        proxy._pyroRelease()
        if master.poll() is None:
            master.kill()
            master.communicate()

    assert status == 1
    assert elapsed < 2
    assert "Incomplete workload" in stderr
    assert not (tmp_path / "ocr_results.csv").exists()


def test_master_skips_oversized_image_and_does_not_publish_complete_csv(tmp_path: Path) -> None:
    images = tmp_path / "images"
    images.mkdir()
    previous_output = b"previous complete output\n"
    (tmp_path / "ocr_results.csv").write_bytes(previous_output)
    oversized = images / "large.png"
    with oversized.open("wb") as stream:
        stream.truncate(MAX_IMAGE_BYTES + 1)

    master, port, _ = _start_master(tmp_path, images)
    proxy = Proxy(f"PYRO:{MASTER_OBJECT_ID}@127.0.0.1:{port}")

    try:
        _wait_for_server(master, port)
        skipped = _rpc(proxy, "get_work", "node", "process", "request")
        shutdown = _rpc(proxy, "get_work", "node", "process", "next")
        assert skipped["status"] == "skip"
        assert shutdown["status"] == "shutdown"
        status, _, stderr = _finish_master(master)
    finally:
        proxy._pyroRelease()
        if master.poll() is None:
            master.kill()
            master.communicate()

    assert status == 1
    assert "1 failed" in stderr
    assert not (tmp_path / "ocr_results.csv").exists()
    assert (tmp_path / "ocr_results.previous.csv").read_bytes() == previous_output
    assert (tmp_path / "ocr_results.partial.csv").exists()
    with (tmp_path / "ocr_failures.csv").open(encoding="utf-8", newline="") as stream:
        failures = list(csv.DictReader(stream))
    assert [(row["image_id"], row["filename"], row["stage"]) for row in failures] == [
        ("1", "large.png", "master_read")
    ]


def test_pyro_message_limit_allows_serpent_base64_expansion(tmp_path: Path) -> None:
    images = tmp_path / "images"
    images.mkdir()
    large_payload = images / "large.png"
    payload_size = 13 * 1024 * 1024
    with large_payload.open("wb") as stream:
        stream.truncate(payload_size)

    master, port, _ = _start_master(tmp_path, images)
    proxy = Proxy(f"PYRO:{MASTER_OBJECT_ID}@127.0.0.1:{port}")

    try:
        _wait_for_server(master, port)
        assignment = _rpc(proxy, "get_work", "node", "process", "request")
        assert assignment["status"] == "work"
        assert len(tobytes(assignment["image_bytes"])) == payload_size
        acknowledgment = _rpc(
            proxy,
            "submit_result",
            "node",
            "process",
            "request",
            assignment["attempt_token"],
            {
                "status": "failure",
                "stage": "transport_test",
                "exception_type": "SyntheticTestFailure",
                "message": "payload transfer assertion",
            },
        )
        assert acknowledgment["status"] == "accepted"
        assert _rpc(proxy, "get_work", "node", "process", "next")["status"] == "shutdown"
        status, _, _ = _finish_master(master)
    finally:
        proxy._pyroRelease()
        if master.poll() is None:
            master.kill()
            master.communicate()

    assert status == 1


def _run_worker_process_against(
    monkeypatch: pytest.MonkeyPatch, master: ScriptedMasterProxy
) -> int:
    monkeypatch.setattr(distributed, "Proxy", lambda _uri: master)
    config = WorkerConfig(master_host="127.0.0.1", master_port=1, n_workers=1)
    return _run_worker_process(config, "test-node", FixedTextRecognizer, threading.Event())


def test_worker_retries_initial_master_connection_until_master_answers(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(distributed, "INITIAL_CONNECT_BASE_DELAY_SECONDS", 0.0)
    master = ScriptedMasterProxy(
        [
            CommunicationError("name resolution failed"),
            CommunicationError("name resolution failed"),
            CommunicationError("name resolution failed"),
            {"status": "shutdown"},
        ]
    )

    assert _run_worker_process_against(monkeypatch, master) == 0

    assert master.get_work_calls == 4
    assert "Cannot reach master" in capsys.readouterr().err


def test_worker_gives_up_after_bounded_initial_retries_when_master_never_answers(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(distributed, "INITIAL_CONNECT_BASE_DELAY_SECONDS", 0.0)
    master = ScriptedMasterProxy([])

    assert _run_worker_process_against(monkeypatch, master) == 1

    assert master.get_work_calls == INITIAL_CONNECT_ATTEMPTS * RPC_ATTEMPTS
    stderr = capsys.readouterr().err
    assert stderr.count("Cannot reach master") == INITIAL_CONNECT_ATTEMPTS - 1
    assert f"no answer after {INITIAL_CONNECT_ATTEMPTS} attempts" in stderr


class StopRequestedMasterProxy:
    """Fail every get_work call and request a stop during the first failed attempt."""

    def __init__(self, stop_event: threading.Event) -> None:
        self._stop_event = stop_event
        self.get_work_calls = 0

    def get_work(self, *args: object) -> dict[str, Any]:
        self.get_work_calls += 1
        self._stop_event.set()
        raise CommunicationError("name resolution failed")

    def _pyroRelease(self) -> None:
        pass


def test_worker_stops_initial_retries_when_stop_is_requested_during_backoff(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    stop_event = threading.Event()
    master = StopRequestedMasterProxy(stop_event)
    monkeypatch.setattr(distributed, "Proxy", lambda _uri: master)
    config = WorkerConfig(master_host="127.0.0.1", master_port=1, n_workers=1)

    assert _run_worker_process(config, "test-node", FixedTextRecognizer, stop_event) == 0

    # One RPC call includes its own explicit retry; no initial backoff retry follows the stop.
    assert master.get_work_calls == RPC_ATTEMPTS
    assert "Cannot request work" not in capsys.readouterr().err


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now


class TimedMasterProxy:
    """Replay scripted get_work outcomes on a fake clock; once exhausted, the master never answers.

    Each call records its start time and the proxy timeout in force. A failing call consumes
    that timeout on the fake clock, as a black-holed master does.
    """

    def __init__(
        self, clock: FakeClock, outcomes: list[dict[str, Any] | Exception] | None = None
    ) -> None:
        self._clock = clock
        self._outcomes = list(outcomes or [])
        self._pyroTimeout = distributed.RPC_TIMEOUT_SECONDS
        self.calls: list[tuple[float, float]] = []

    def get_work(self, *args: object) -> dict[str, Any]:
        self.calls.append((self._clock.now, self._pyroTimeout))
        outcome = (
            self._outcomes.pop(0)
            if self._outcomes
            else CommunicationError("no response before the RPC timeout")
        )
        if isinstance(outcome, Exception):
            self._clock.now += self._pyroTimeout
            raise outcome
        return outcome

    def _pyroRelease(self) -> None:
        pass


def _use_fake_clock(monkeypatch: pytest.MonkeyPatch, clock: FakeClock) -> None:
    monkeypatch.setattr(
        distributed,
        "time",
        SimpleNamespace(monotonic=clock.monotonic, sleep=lambda _seconds: None),
    )
    monkeypatch.setattr(distributed, "INITIAL_CONNECT_BASE_DELAY_SECONDS", 0.0)


def test_rpc_call_with_passed_deadline_raises_without_calling_master() -> None:
    master = TimedMasterProxy(FakeClock())

    with pytest.raises(CommunicationError, match="deadline passed"):
        distributed._rpc_call(
            cast(Proxy, master), "get_work", "node", "process", "request", deadline=float("-inf")
        )

    assert master.calls == []


def test_worker_bounds_initial_connect_to_total_deadline_when_master_is_black_holed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    clock = FakeClock()
    _use_fake_clock(monkeypatch, clock)
    master = TimedMasterProxy(clock)
    monkeypatch.setattr(distributed, "Proxy", lambda _uri: master)
    config = WorkerConfig(master_host="127.0.0.1", master_port=1, n_workers=1)

    assert _run_worker_process(config, "test-node", FixedTextRecognizer, threading.Event()) == 1

    assert clock.now <= distributed.INITIAL_CONNECT_DEADLINE_SECONDS
    assert "no answer after 45 s" in capsys.readouterr().err


def test_worker_caps_each_initial_call_timeout_to_the_remaining_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    _use_fake_clock(monkeypatch, clock)
    master = TimedMasterProxy(clock)
    monkeypatch.setattr(distributed, "Proxy", lambda _uri: master)
    config = WorkerConfig(master_host="127.0.0.1", master_port=1, n_workers=1)

    assert _run_worker_process(config, "test-node", FixedTextRecognizer, threading.Event()) == 1

    assert master.calls
    deadline = distributed.INITIAL_CONNECT_DEADLINE_SECONDS
    for start, timeout in master.calls:
        assert start + timeout <= deadline, f"call at {start} s may wait until {start + timeout} s"


def test_worker_restores_rpc_timeout_after_first_master_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    _use_fake_clock(monkeypatch, clock)
    no_response = CommunicationError("no response before the RPC timeout")
    master = TimedMasterProxy(
        clock, [no_response, no_response, {"status": "wait"}, {"status": "shutdown"}]
    )
    monkeypatch.setattr(distributed, "Proxy", lambda _uri: master)
    config = WorkerConfig(master_host="127.0.0.1", master_port=1, n_workers=1)

    assert _run_worker_process(config, "test-node", FixedTextRecognizer, threading.Event()) == 0

    # The last call is the first one after the master answered: it must get the full 20 s again.
    assert master.calls[-1][1] == distributed.RPC_TIMEOUT_SECONDS


def test_worker_restores_rpc_timeout_when_initial_connect_gives_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    _use_fake_clock(monkeypatch, clock)
    master = TimedMasterProxy(clock)
    monkeypatch.setattr(distributed, "Proxy", lambda _uri: master)
    config = WorkerConfig(master_host="127.0.0.1", master_port=1, n_workers=1)

    assert _run_worker_process(config, "test-node", FixedTextRecognizer, threading.Event()) == 1

    assert master._pyroTimeout == distributed.RPC_TIMEOUT_SECONDS


def test_worker_exits_on_connection_failure_after_master_has_answered(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    master = ScriptedMasterProxy([{"status": "wait"}])

    assert _run_worker_process_against(monkeypatch, master) == 1

    assert master.get_work_calls == 1 + RPC_ATTEMPTS
    assert "Cannot reach master" not in capsys.readouterr().err


def test_master_request_loop_polls_often_enough_to_exit_promptly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    images = tmp_path / "images"
    images.mkdir()
    Image.new("RGB", (8, 8)).save(images / "page.png")
    config = tmp_path / "master_config.txt"
    config.write_text(f"image_dir={images}\nport={_free_port()}\n", encoding="utf-8")
    poll_seconds_seen: list[float] = []

    class RecordingDaemon:
        def __init__(self, host: str, port: int) -> None:
            pass

        def register(self, obj: object, objectId: str) -> str:
            return f"PYRO:{objectId}@localhost:0"

        def requestLoop(self, loopCondition: Any) -> None:
            poll_seconds_seen.append(distributed.Pyro5.api.config.POLLTIMEOUT)

        def close(self) -> None:
            pass

    monkeypatch.setattr(distributed.Pyro5.api, "Daemon", RecordingDaemon)
    # Restored after the test; run_master is expected to set it for the master process.
    monkeypatch.setattr(distributed.Pyro5.api.config, "POLLTIMEOUT", 2.0)

    distributed.run_master(config)

    # With POLLTIMEOUT at 2.0 s, a finished master can keep serving for up to 2 s after its
    # shutdown condition flips. The bound keeps that tail well under a second.
    assert len(poll_seconds_seen) == 1
    assert poll_seconds_seen[0] <= 0.5
