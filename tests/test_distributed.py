from __future__ import annotations

import csv
import multiprocessing
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from PIL import Image
from Pyro5.api import Proxy
from serpent import tobytes

from parallel_ocr_pipeline.distributed import MASTER_OBJECT_ID, MAX_IMAGE_BYTES, run_worker

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


def _worker_child(config_path: str) -> None:
    raise SystemExit(run_worker(config_path, recognizer_factory=FixedTextRecognizer))


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


def test_pyro_work_request_replays_same_image_and_result_ack_is_idempotent(
    tmp_path: Path,
) -> None:
    images = tmp_path / "images"
    images.mkdir()
    image_path = images / "one.png"
    _write_image(image_path)
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

        first = _rpc(proxy, "get_work", "node", "process", "request")
        replay = _rpc(proxy, "get_work", "node", "process", "request")
        assert first["status"] == "work"
        assert replay["status"] == "work"
        assert replay["attempt_token"] == first["attempt_token"]
        assert tobytes(first["image_bytes"]) == image_path.read_bytes()
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
        completed = _rpc(proxy, "get_work", "node", "process", first["request_id"])
        shutdown = _rpc(proxy, "get_work", "node", "process", "next")
        assert completed["status"] == "completed"
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
        ("1", "one.png", "recognized")
    ]


def test_master_skips_oversized_image_and_does_not_publish_complete_csv(tmp_path: Path) -> None:
    images = tmp_path / "images"
    images.mkdir()
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
