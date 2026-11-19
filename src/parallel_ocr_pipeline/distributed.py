"""Direct-Pyro5 master/worker OCR workload for the first distributed slice."""

from __future__ import annotations

import csv
import io
import math
import multiprocessing
import multiprocessing.process
import os
import queue
import re
import signal
import socket
import sys
import threading
import time
import traceback
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import Pyro5.api
import Pyro5.errors
import serpent
from PIL import Image
from Pyro5.api import Proxy
from Pyro5.errors import CommunicationError

from parallel_ocr_pipeline.config import ConfigError, InputImage, enumerate_images
from parallel_ocr_pipeline.distributed_config import (
    DistributedConfigError,
    MasterConfig,
    WorkerConfig,
    load_master_config,
    load_worker_config,
)
from parallel_ocr_pipeline.recognizer import RecognitionTimeoutError, TesseractRecognizer

MASTER_OBJECT_ID = "ocr.master"
MAX_IMAGE_BYTES = 16 * 1024 * 1024
MAX_RPC_MESSAGE_BYTES = MAX_IMAGE_BYTES * 2 + 256 * 1024
MAX_TEXT_CHARS = 1_000_000
MAX_DIAGNOSTIC_CHARS = 2_000
MAX_ACTIVE_WORKERS = 32
RPC_TIMEOUT_SECONDS = 20.0
RPC_ATTEMPTS = 2
RPC_RETRY_DELAY_SECONDS = 0.2
WORK_POLL_SECONDS = 0.2
MASTER_STARTUP_TIMEOUT_SECONDS = 60.0
MASTER_IDLE_TIMEOUT_SECONDS = 180.0

_IDENTIFIER = re.compile(r"[A-Za-z0-9_.:@-]{1,160}\Z")
_RESULT_FIELDS = {"status", "text", "processing_time_ms"}
_FAILURE_FIELDS = {"status", "stage", "exception_type", "message"}
CSV_FIELDS = ("image_id", "filename", "text", "processing_time_ms")
FAILURE_CSV_FIELDS = ("image_id", "filename", "stage", "exception_type", "message")


@dataclass(slots=True)
class _Assignment:
    image: InputImage
    node_id: str
    process_id: str
    request_id: str
    token: str
    outcome: dict[str, Any] | None = None


class MasterCoordinator:
    """Thread-safe RPC object; filesystem reads happen outside its condition lock."""

    def __init__(
        self,
        config: MasterConfig,
        *,
        startup_timeout: float = MASTER_STARTUP_TIMEOUT_SECONDS,
        idle_timeout: float = MASTER_IDLE_TIMEOUT_SECONDS,
    ) -> None:
        self._images = enumerate_images(config.image_dir)
        self._config = config
        self._available: queue.Queue[InputImage] = queue.Queue()
        for image in self._images:
            self._available.put_nowait(image)

        self._condition = threading.Condition()
        self._requests: dict[tuple[str, str, str], dict[str, Any]] = {}
        self._building_requests: set[tuple[str, str, str]] = set()
        self._assignments: dict[str, _Assignment] = {}
        self._active_by_process: dict[tuple[str, str], str] = {}
        self._records: dict[int, dict[str, Any]] = {}
        self._failures: dict[int, dict[str, Any]] = {}
        self._result_acks: dict[tuple[str, str, str], tuple[dict[str, Any], dict[str, Any]]] = {}
        self._stop_event = threading.Event()
        self._created_at = time.monotonic()
        self._last_progress = self._created_at
        self._startup_timeout = startup_timeout
        self._idle_timeout = idle_timeout
        self._fatal_reason: str | None = None
        self._worker_seen = False

    @Pyro5.api.expose
    def get_work(self, node_id: str, process_id: str, request_id: str) -> dict[str, Any]:
        """Return one byte payload, a wait instruction, or bounded shutdown."""
        if not all(_valid_identifier(value) for value in (node_id, process_id, request_id)):
            return _rejected("node_id, process_id, and request_id must be bounded identifiers")

        key = (node_id, process_id, request_id)
        process_key = (node_id, process_id)
        with self._condition:
            while key in self._building_requests:
                self._condition.wait(timeout=RPC_TIMEOUT_SECONDS)
            previous = self._requests.get(key)
            if previous is not None:
                return previous.copy()

            if self._stop_event.is_set():
                return {"status": "shutdown"}

            if process_key in self._active_by_process:
                response = {"status": "wait"}
                self._requests[key] = response
                return response.copy()
            if len(self._active_by_process) >= MAX_ACTIVE_WORKERS:
                return _rejected("master reached the active worker-process limit")

            try:
                image = self._available.get_nowait()
            except queue.Empty:
                if not self._has_active_assignments_locked():
                    response = {"status": "shutdown"}
                    self._requests[key] = response
                    self._stop_event.set()
                    self._condition.notify_all()
                    return response.copy()
                response = {"status": "wait"}
                self._requests[key] = response
                return response.copy()

            assignment = _Assignment(
                image=image,
                node_id=node_id,
                process_id=process_id,
                request_id=request_id,
                token=uuid.uuid4().hex,
            )
            self._assignments[assignment.token] = assignment
            self._active_by_process[process_key] = assignment.token
            self._building_requests.add(key)
            self._worker_seen = True
            self._last_progress = time.monotonic()

        response = self._read_assignment(assignment)
        with self._condition:
            if response["status"] == "skip":
                self._failures[image.image_id] = {
                    "image_id": image.image_id,
                    "filename": image.path.name,
                    "stage": response["stage"],
                    "exception_type": response["exception_type"],
                    "message": response["message"],
                }
                assignment.outcome = {"status": "source_failure"}
                del self._assignments[assignment.token]
                self._active_by_process.pop((assignment.node_id, assignment.process_id), None)
                self._last_progress = time.monotonic()
            else:
                self._last_progress = time.monotonic()
            self._requests[key] = response
            self._building_requests.remove(key)
            self._condition.notify_all()
            return response.copy()

    @Pyro5.api.expose
    def submit_result(
        self,
        node_id: str,
        process_id: str,
        request_id: str,
        attempt_token: str,
        outcome: object,
    ) -> dict[str, Any]:
        """Accept one validated result/failure; exact duplicate submissions are safe."""
        if not all(
            _valid_identifier(value) for value in (node_id, process_id, request_id, attempt_token)
        ):
            return _rejected("worker identity, request_id, or attempt_token is invalid")
        normalized = _validate_outcome(outcome)
        if normalized is None:
            return _rejected("outcome has an invalid shape or exceeds the application bounds")

        ack_key = (node_id, process_id, request_id)
        with self._condition:
            previous = self._result_acks.get(ack_key)
            if previous is not None:
                if previous[0] == normalized and previous[1]["attempt_token"] == attempt_token:
                    return {"status": "accepted", "duplicate": True}
                return _rejected("request_id was already used for a different result")

            assignment = self._assignments.get(attempt_token)
            if (
                assignment is None
                or assignment.node_id != node_id
                or assignment.process_id != process_id
                or assignment.request_id != request_id
                or assignment.outcome is not None
            ):
                return _rejected(
                    "attempt_token is unknown, completed, or belongs to another request"
                )

            assignment.outcome = normalized
            image = assignment.image
            if normalized["status"] == "success":
                self._records[image.image_id] = {
                    "image_id": image.image_id,
                    "filename": image.path.name,
                    "text": normalized["text"],
                    "processing_time_ms": f"{normalized['processing_time_ms']:.3f}",
                }
            else:
                self._failures[image.image_id] = {
                    "image_id": image.image_id,
                    "filename": image.path.name,
                    "stage": normalized["stage"],
                    "exception_type": normalized["exception_type"],
                    "message": normalized["message"],
                }
            ack = {"status": "accepted", "duplicate": False}
            self._result_acks[ack_key] = (normalized, {"attempt_token": attempt_token})
            self._assignments.pop(attempt_token, None)
            self._active_by_process.pop((node_id, process_id), None)
            # The result closes the request; discard its potentially large image payload.
            self._requests[(node_id, process_id, request_id)] = {"status": "completed"}
            self._last_progress = time.monotonic()
            self._condition.notify_all()
            return ack

    def should_continue(self) -> bool:
        """Pyro's loop condition: continue until shutdown or a finite deadline."""
        if self._stop_event.is_set():
            return False
        now = time.monotonic()
        if not self._worker_seen and now - self._created_at >= self._startup_timeout:
            self.stop("no worker connected before the startup deadline")
        elif self._worker_seen and now - self._last_progress >= self._idle_timeout:
            self.stop("worker became inactive before the workload completed")
        return not self._stop_event.is_set()

    def stop(self, reason: str) -> None:
        """Stop accepting work and retain a reason for the incomplete-run artifacts."""
        self._fatal_reason = reason
        self._stop_event.set()
        with self._condition:
            self._condition.notify_all()

    def prepare_outputs(self) -> None:
        """Move an older complete CSV aside before starting this workload."""
        self._config.output_dir.mkdir(parents=True, exist_ok=True)
        results_path = self._config.output_dir / "ocr_results.csv"
        previous_path = self._config.output_dir / "ocr_results.previous.csv"
        if results_path.exists():
            results_path.replace(previous_path)

    def write_outputs(self) -> bool:
        """Publish complete CSV only when every discovered image succeeded."""
        with self._condition:
            complete = len(self._records) == len(self._images) and not self._failures
            records = [self._records[key].copy() for key in sorted(self._records)]
            failures = [self._failures[key].copy() for key in sorted(self._failures)]
            known_ids = set(self._records) | set(self._failures)
            for image in self._images:
                if image.image_id not in known_ids:
                    failures.append(
                        {
                            "image_id": image.image_id,
                            "filename": image.path.name,
                            "stage": "incomplete",
                            "exception_type": "WorkloadIncomplete",
                            "message": self._fatal_reason
                            or "master stopped before a result arrived",
                        }
                    )

        output_dir = self._config.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        results_path = output_dir / "ocr_results.csv"
        partial_path = output_dir / "ocr_results.partial.csv"
        failures_path = output_dir / "ocr_failures.csv"
        if complete:
            _write_csv_atomic(results_path, CSV_FIELDS, records)
            _remove_if_exists(partial_path)
            _remove_if_exists(failures_path)
            _remove_if_exists(output_dir / "ocr_results.previous.csv")
            return True

        _write_csv_atomic(partial_path, CSV_FIELDS, records)
        _write_csv_atomic(failures_path, FAILURE_CSV_FIELDS, failures)
        return False

    def _read_assignment(self, assignment: _Assignment) -> dict[str, Any]:
        path = assignment.image.path
        try:
            size = path.stat().st_size
            if size > MAX_IMAGE_BYTES:
                raise ValueError(f"image exceeds the {MAX_IMAGE_BYTES}-byte transfer limit")
            payload = path.read_bytes()
            if len(payload) > MAX_IMAGE_BYTES:
                raise ValueError(f"image exceeds the {MAX_IMAGE_BYTES}-byte transfer limit")
        except (OSError, ValueError) as error:
            return {
                "status": "skip",
                "stage": "master_read",
                "exception_type": type(error).__name__,
                "message": str(error)[:MAX_DIAGNOSTIC_CHARS],
            }
        return {
            "status": "work",
            "image_id": assignment.image.image_id,
            "filename": path.name,
            "image_bytes": payload,
            "request_id": assignment.request_id,
            "attempt_token": assignment.token,
        }

    def _has_active_assignments_locked(self) -> bool:
        return bool(self._active_by_process)


def run_master(config_path: str | Path) -> int:
    """Run the threaded Pyro daemon and publish success or incomplete artifacts."""
    try:
        config = load_master_config(config_path)
        coordinator = MasterCoordinator(config)
    except (DistributedConfigError, ConfigError) as error:
        print(f"Master configuration error: {error}", file=sys.stderr)
        return 2

    try:
        coordinator.prepare_outputs()
    except OSError as error:
        print(f"Master cannot prepare output files: {error}", file=sys.stderr)
        return 2

    daemon: Pyro5.api.Daemon | None = None
    try:
        Pyro5.api.config.MAX_MESSAGE_SIZE = (  # pyright: ignore[reportAttributeAccessIssue]
            MAX_RPC_MESSAGE_BYTES
        )
        daemon = Pyro5.api.Daemon(host="0.0.0.0", port=config.port)
        uri = daemon.register(coordinator, objectId=MASTER_OBJECT_ID)
        print(f"Master ready at {uri}; queued {len(coordinator._images)} image(s).", flush=True)
        daemon.requestLoop(loopCondition=coordinator.should_continue)
    except KeyboardInterrupt:
        coordinator.stop("master interrupted by operator")
    except (OSError, Pyro5.errors.PyroError) as error:
        coordinator.stop(f"Pyro master error: {type(error).__name__}: {error}")
        print(coordinator._fatal_reason, file=sys.stderr)
    finally:
        if daemon is not None:
            daemon.close()

    complete = coordinator.write_outputs()
    if complete:
        print(f"Completed {len(coordinator._images)} image(s).", flush=True)
        return 0
    print(
        f"Incomplete workload: {len(coordinator._records)} succeeded, "
        f"{len(coordinator._failures)} failed; see partial and failure CSV files.",
        file=sys.stderr,
        flush=True,
    )
    return 1


def run_worker(
    config_path: str | Path,
    *,
    recognizer_factory: Callable[[], Any] = TesseractRecognizer,
) -> int:
    """Start and supervise the configured spawn-based worker processes."""
    try:
        config = load_worker_config(config_path)
    except DistributedConfigError as error:
        print(f"Worker configuration error: {error}", file=sys.stderr)
        return 2
    context = multiprocessing.get_context("spawn")
    stop_event = context.Event()
    node_id = socket.gethostname()
    children = [
        context.Process(
            name=f"ocr-worker-{index + 1}",
            target=_worker_process_entry,
            args=(config, node_id, recognizer_factory, stop_event),
        )
        for index in range(config.n_workers)
    ]
    started: list[multiprocessing.process.BaseProcess] = []
    failed = False
    interrupted = False
    termination_signal: int | None = None

    def handle_sigterm(signum: int, _frame: Any) -> None:
        nonlocal interrupted, termination_signal
        interrupted = True
        termination_signal = signum

    previous_sigterm_handler = signal.signal(signal.SIGTERM, handle_sigterm)
    try:
        for child in children:
            if interrupted:
                break
            child.start()
            started.append(child)

        running = set(started)
        while running and not interrupted:
            for child in tuple(running):
                child.join(timeout=0)
                if child.exitcode is None:
                    continue
                running.remove(child)
                if child.exitcode != 0:
                    failed = True
                    stop_event.set()
                    break
            if failed:
                break
            if running:
                time.sleep(0.05)
    except KeyboardInterrupt:
        interrupted = True
        stop_event.set()
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Cannot start worker processes: {error}", file=sys.stderr)
        failed = True
        stop_event.set()
    finally:
        if failed or interrupted:
            stop_event.set()
        _join_worker_processes(started)
        signal.signal(signal.SIGTERM, previous_sigterm_handler)

    if termination_signal is not None:
        return 128 + termination_signal
    return 130 if interrupted else 1 if failed else 0


def _worker_process_entry(
    config: WorkerConfig,
    node_id: str,
    recognizer_factory: Callable[[], Any],
    stop_event: Any,
) -> None:
    """Initialize process-owned OCR and RPC resources, then run one pull loop."""
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        raise SystemExit(_run_worker_process(config, node_id, recognizer_factory, stop_event))
    except Exception as error:
        print(
            f"Worker process failed: {type(error).__name__}: {error}\n{traceback.format_exc()}",
            file=sys.stderr,
            flush=True,
        )
        raise SystemExit(1) from error


def _run_worker_process(
    config: WorkerConfig,
    node_id: str,
    recognizer_factory: Callable[[], Any],
    stop_event: Any,
) -> int:
    """Pull and acknowledge one image at a time using process-local resources."""
    process_id = f"{os.getpid()}:{uuid.uuid4().hex}"
    os.environ.setdefault("OMP_THREAD_LIMIT", "1")
    uri = _master_uri(config)
    Pyro5.api.config.MAX_MESSAGE_SIZE = MAX_RPC_MESSAGE_BYTES  # pyright: ignore[reportAttributeAccessIssue]
    proxy = Proxy(uri)
    proxy._pyroTimeout = RPC_TIMEOUT_SECONDS
    proxy._pyroMaxRetries = 0
    try:
        recognizer = recognizer_factory()
        while not stop_event.is_set():
            request_id = uuid.uuid4().hex
            try:
                response = _rpc_call(proxy, "get_work", node_id, process_id, request_id)
            except CommunicationError as error:
                print(f"Cannot request work from master: {error}", file=sys.stderr)
                return 1

            status = response.get("status")
            if status == "shutdown":
                return 0
            if status == "wait":
                stop_event.wait(WORK_POLL_SECONDS)
                continue
            if status == "skip":
                continue
            if status == "rejected":
                print(
                    f"Master rejected work request: {response.get('message', 'invalid request')}",
                    file=sys.stderr,
                )
                return 1
            if status != "work":
                print(f"Master returned an invalid work response: {status!r}", file=sys.stderr)
                return 1

            assignment_request_id = response.get("request_id")
            attempt_token = response.get("attempt_token")
            image_id = response.get("image_id")
            filename = response.get("filename")
            if (
                not isinstance(assignment_request_id, str)
                or assignment_request_id != request_id
                or not isinstance(attempt_token, str)
                or not isinstance(image_id, int)
                or not isinstance(filename, str)
            ):
                print("Master returned malformed assignment metadata.", file=sys.stderr)
                return 1

            outcome = _recognize_assignment(response, recognizer)
            try:
                acknowledgment = _rpc_call(
                    proxy,
                    "submit_result",
                    node_id,
                    process_id,
                    request_id,
                    attempt_token,
                    outcome,
                )
            except CommunicationError as error:
                print(f"Cannot submit result for image {image_id}: {error}", file=sys.stderr)
                return 1
            if acknowledgment.get("status") != "accepted":
                print(
                    f"Master rejected result for image {image_id}: "
                    f"{acknowledgment.get('message', 'invalid acknowledgment')}",
                    file=sys.stderr,
                )
                return 1
        return 0
    finally:
        proxy._pyroRelease()


def _join_worker_processes(children: list[multiprocessing.process.BaseProcess]) -> None:
    """Join children and bound cleanup if a sibling or operator stopped the node."""
    graceful_deadline = time.monotonic() + RPC_TIMEOUT_SECONDS * RPC_ATTEMPTS + 1
    for child in children:
        remaining = max(0.0, graceful_deadline - time.monotonic())
        child.join(timeout=remaining)
    for child in children:
        if child.is_alive():
            child.terminate()
            child.join(timeout=5)
        if child.exitcode is not None:
            child.close()


def _recognize_assignment(response: dict[str, Any], recognizer: Any) -> dict[str, Any]:
    image_id = response.get("image_id", "?")
    try:
        raw_payload = response.get("image_bytes")
        if isinstance(raw_payload, bytes):
            payload = raw_payload
        elif isinstance(raw_payload, dict):
            payload = serpent.tobytes(raw_payload)
        else:
            raise TypeError("image payload is not encoded bytes")
        if len(payload) > MAX_IMAGE_BYTES:
            raise ValueError("image payload exceeds the application transfer limit")
    except (TypeError, ValueError) as error:
        return _failure_outcome("decode", image_id, error)

    try:
        image = Image.open(io.BytesIO(payload))
        image.load()
    except (OSError, ValueError, Image.DecompressionBombError) as error:
        return _failure_outcome("decode", image_id, error)

    with image:
        try:
            started = time.perf_counter_ns()
            for attempt in range(2):
                try:
                    text = recognizer.recognize(image)
                    break
                except RecognitionTimeoutError:
                    if attempt == 1:
                        raise
            else:
                raise RuntimeError("recognition did not produce a result")
            elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
        except Exception as error:  # noqa: BLE001 - recognizer failures become per-image outcomes
            return _failure_outcome("recognition", image_id, error)

    if not isinstance(text, str) or len(text) > MAX_TEXT_CHARS:
        return _failure_outcome(
            "recognition", image_id, ValueError("recognizer text exceeds its application bound")
        )
    return {
        "status": "success",
        "text": text,
        "processing_time_ms": elapsed_ms,
    }


def _failure_outcome(stage: str, image_id: object, error: Exception) -> dict[str, Any]:
    return {
        "status": "failure",
        "stage": stage,
        "exception_type": type(error).__name__[:128],
        "message": f"image {image_id}: {error}"[:MAX_DIAGNOSTIC_CHARS],
    }


def _rpc_call(proxy: Proxy, method: str, *args: object) -> dict[str, Any]:
    """Retry one RPC explicitly with the same idempotency key on a child-owned proxy."""
    last_error: CommunicationError | None = None
    for attempt in range(RPC_ATTEMPTS):
        try:
            result = getattr(proxy, method)(*args)
            if not isinstance(result, dict):
                raise CommunicationError("master returned a non-dictionary RPC response")
            return result
        except CommunicationError as error:
            last_error = error
            proxy._pyroRelease()
            if attempt + 1 < RPC_ATTEMPTS:
                time.sleep(RPC_RETRY_DELAY_SECONDS * (attempt + 1))
    assert last_error is not None
    raise last_error


def _master_uri(config: WorkerConfig) -> str:
    return f"PYRO:{MASTER_OBJECT_ID}@{config.master_host}:{config.master_port}"


def _validate_outcome(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    status = value.get("status")
    if status == "success" and set(value) == _RESULT_FIELDS:
        text = value.get("text")
        processing_time = value.get("processing_time_ms")
        if (
            not isinstance(text, str)
            or len(text) > MAX_TEXT_CHARS
            or not isinstance(processing_time, (int, float))
            or isinstance(processing_time, bool)
        ):
            return None
        try:
            processing_time_ms = float(processing_time)
        except OverflowError, ValueError:
            return None
        if not math.isfinite(processing_time_ms) or processing_time_ms < 0:
            return None
        return {
            "status": "success",
            "text": text,
            "processing_time_ms": processing_time_ms,
        }
    if status == "failure" and set(value) == _FAILURE_FIELDS:
        stage = value.get("stage")
        exception_type = value.get("exception_type")
        message = value.get("message")
        if (
            not isinstance(stage, str)
            or not stage
            or len(stage) > 128
            or not isinstance(exception_type, str)
            or not exception_type
            or len(exception_type) > 128
            or not isinstance(message, str)
            or len(message) > MAX_DIAGNOSTIC_CHARS
        ):
            return None
        return {
            "status": "failure",
            "stage": stage,
            "exception_type": exception_type,
            "message": message,
        }
    return None


def _valid_identifier(value: object) -> bool:
    return isinstance(value, str) and _IDENTIFIER.fullmatch(value) is not None


def _rejected(message: str) -> dict[str, Any]:
    return {"status": "rejected", "message": message[:MAX_DIAGNOSTIC_CHARS]}


def _write_csv_atomic(path: Path, fields: tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def _remove_if_exists(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
