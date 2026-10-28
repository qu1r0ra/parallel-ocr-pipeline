from __future__ import annotations

import csv
import json
import os
import re
import subprocess
import sys
import textwrap
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Literal

import pytest
from PIL import Image

from conftest import DeterministicRecognizer
from parallel_ocr_pipeline.pipeline import run
from parallel_ocr_pipeline.recognizer import (
    PrerequisiteError,
    RecognitionFailedError,
    RecognitionTimeoutError,
)


class ScriptedRecognizer:
    """Return or raise planned outcomes for each image marker."""

    def __init__(self, outcomes: dict[int, list[str | Exception]]) -> None:
        self._outcomes = outcomes
        self._attempts: dict[int, int] = {}
        self._images: dict[int, list[Image.Image]] = {}
        self._lock = threading.Lock()

    def recognize(self, image: Image.Image, /) -> str:
        pixel = image.getpixel((0, 0))
        assert isinstance(pixel, tuple) and isinstance(pixel[0], int)
        marker = pixel[0]
        with self._lock:
            attempt = self._attempts.get(marker, 0)
            self._attempts[marker] = attempt + 1
            self._images.setdefault(marker, []).append(image)
            outcome = self._outcomes[marker][attempt]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def attempts_for(self, marker: int) -> int:
        return self._attempts.get(marker, 0)

    def images_for(self, marker: int) -> tuple[Image.Image, ...]:
        with self._lock:
            return tuple(self._images.get(marker, ()))


def _write_config(tmp_path: Path, image_dir: Path, n_workers: int = 1) -> Path:
    config_path = tmp_path / "config.txt"
    config_path.write_text(
        f"image_dir={image_dir}\nn_workers={n_workers}\n",
        encoding="utf-8",
    )
    return config_path


@pytest.mark.parametrize("n_workers", [1, 3])
def test_run_writes_associated_csv_rows_and_closes_images_and_threads(
    tmp_path: Path,
    n_workers: int,
    pipeline_image_writer: Callable[[Path, int], Path],
    deterministic_recognizer_factory: type[DeterministicRecognizer],
) -> None:
    """Write one escaped, correctly identified result per image and join all threads."""
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    names_and_markers = [("charlie.png", 3), ("alpha.png", 1), ("bravo.png", 2)]
    for filename, marker in names_and_markers:
        pipeline_image_writer(image_dir / filename, marker)

    config_path = tmp_path / "config.txt"
    config_path.write_text(f"image_dir={image_dir}\nn_workers={n_workers}\n", encoding="utf-8")
    (tmp_path / "ocr_results.partial.csv").write_text("stale partial\n", encoding="utf-8")
    (tmp_path / "ocr_failures.csv").write_text("stale failures\n", encoding="utf-8")
    expected_text = {
        1: 'comma, quote " and\nnewline',
        2: "second image",
        3: "third image",
    }
    recognizer = deterministic_recognizer_factory(
        expected_text,
        threading.Barrier(n_workers),
        slow_marker=1 if n_workers > 1 else None,
    )

    assert run(config_path, recognizer) == 0

    with (tmp_path / "ocr_results.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))

    row_ids = [row["image_id"] for row in rows]
    assert len(row_ids) == 3
    assert len(set(row_ids)) == 3
    assert {row["image_id"] for row in rows} == {"1", "2", "3"}
    if n_workers > 1:
        assert row_ids != ["1", "2", "3"]
    assert {row["filename"]: row["text"] for row in rows} == {
        "alpha.png": expected_text[1],
        "bravo.png": expected_text[2],
        "charlie.png": expected_text[3],
    }
    assert all(float(row["processing_time_ms"]) >= 0 for row in rows)
    assert len(recognizer.threads) == n_workers
    assert all(not thread.is_alive() for thread in recognizer.threads)
    assert all(_is_closed(image) for image in recognizer.images)
    assert recognizer.max_active == n_workers
    assert not list(tmp_path.glob(".ocr_results.*.tmp"))
    assert not (tmp_path / "ocr_results.partial.csv").exists()
    assert not (tmp_path / "ocr_failures.csv").exists()


def _is_closed(image: Image.Image) -> bool:
    with pytest.raises(ValueError):
        image.getpixel((0, 0))
    return True


def test_run_reports_total_processing_time_after_publication(
    tmp_path: Path,
    pipeline_image_writer: Callable[[Path, int], Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Report full-run elapsed time separately from per-image CSV timings."""
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    pipeline_image_writer(image_dir / "alpha.png", 1)
    config_path = _write_config(tmp_path, image_dir)

    assert run(config_path, ScriptedRecognizer({1: ["recognized"]})) == 0

    assert re.search(r"Total processing time: [0-9]+\.[0-9]{3} seconds", capsys.readouterr().out)
    assert (tmp_path / "ocr_results.csv").is_file()


def test_run_retries_timed_out_recognition_and_accepts_empty_text(
    tmp_path: Path,
    pipeline_image_writer: Callable[[Path, int], Path],
) -> None:
    """A recovered timeout produces one successful row, including for empty OCR text."""
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    pipeline_image_writer(image_dir / "alpha.png", 1)
    pipeline_image_writer(image_dir / "beta.png", 2)
    config_path = _write_config(tmp_path, image_dir)
    recognizer = ScriptedRecognizer(
        {
            1: [RecognitionTimeoutError("temporary timeout"), ""],
            2: ["recognized"],
        }
    )

    assert run(config_path, recognizer) == 0

    with (tmp_path / "ocr_results.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert [(row["filename"], row["text"]) for row in rows] == [
        ("alpha.png", ""),
        ("beta.png", "recognized"),
    ]
    assert recognizer.attempts_for(1) == 2
    assert recognizer.attempts_for(2) == 1
    retried_images = recognizer.images_for(1)
    assert len(retried_images) == 2
    assert retried_images[0] is retried_images[1]
    assert getattr(retried_images[0], "fp", None) is None
    assert _is_closed(retried_images[0])


def test_run_reports_successful_loader_and_recognition_retries(
    tmp_path: Path,
    pipeline_image_writer: Callable[[Path, int], Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The public run output summarizes recoveries from both retry stages."""
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    alpha_path = pipeline_image_writer(image_dir / "alpha.png", 1)
    pipeline_image_writer(image_dir / "beta.png", 2)
    config_path = _write_config(tmp_path, image_dir)
    recognizer = ScriptedRecognizer(
        {
            1: ["alpha"],
            2: [RecognitionTimeoutError("temporary timeout"), "beta"],
        }
    )
    original_open = Image.open
    denied_once = False

    def open_with_temporary_denial(
        file: Path,
        mode: Literal["r"] = "r",
        formats: list[str] | tuple[str, ...] | None = None,
    ) -> Image.Image:
        nonlocal denied_once
        if Path(file) == alpha_path and not denied_once:
            denied_once = True
            raise PermissionError("file is temporarily locked")
        return original_open(file, mode=mode, formats=formats)

    monkeypatch.setattr(Image, "open", open_with_temporary_denial)

    assert run(config_path, recognizer) == 0

    assert "Recovery activity: loader retries=1, recognition retries=1" in capsys.readouterr().out


def test_run_reports_image_failures_and_continues_other_images(
    tmp_path: Path,
    pipeline_image_writer: Callable[[Path, int], Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Exhausted and terminal image errors are reported while later images still succeed."""
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    pipeline_image_writer(image_dir / "alpha-timeout.png", 1)
    pipeline_image_writer(image_dir / "beta-terminal.png", 2)
    pipeline_image_writer(image_dir / "charlie-success.png", 3)
    config_path = _write_config(tmp_path, image_dir)
    successful_output = tmp_path / "ocr_results.csv"
    successful_output.write_text("previous complete run\n", encoding="utf-8")
    recognizer = ScriptedRecognizer(
        {
            1: [
                RecognitionTimeoutError("first timeout"),
                RecognitionTimeoutError("second timeout"),
            ],
            2: [RecognitionFailedError("bad image content")],
            3: ["later image succeeded"],
        }
    )

    assert run(config_path, recognizer) == 1

    with (tmp_path / "ocr_results.partial.csv").open(encoding="utf-8", newline="") as stream:
        partial_rows = list(csv.DictReader(stream))
    assert [(row["filename"], row["text"]) for row in partial_rows] == [
        ("charlie-success.png", "later image succeeded")
    ]
    with (tmp_path / "ocr_failures.csv").open(encoding="utf-8", newline="") as stream:
        failures = list(csv.DictReader(stream))
    assert failures == [
        {
            "image_id": "1",
            "filename": "alpha-timeout.png",
            "stage": "recognize",
            "attempts": "2",
            "exception_type": "RecognitionTimeoutError",
            "message": "second timeout",
        },
        {
            "image_id": "2",
            "filename": "beta-terminal.png",
            "stage": "recognize",
            "attempts": "1",
            "exception_type": "RecognitionFailedError",
            "message": "bad image content",
        },
    ]
    assert successful_output.read_text(encoding="utf-8") == "previous complete run\n"
    assert "previous successful run" in capsys.readouterr().err


def test_run_retries_temporary_image_access_denial(
    tmp_path: Path,
    pipeline_image_writer: Callable[[Path, int], Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A temporary file-access denial is retried by the loader."""
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    image_path = pipeline_image_writer(image_dir / "alpha.png", 1)
    config_path = _write_config(tmp_path, image_dir)
    recognizer = ScriptedRecognizer({1: ["recognized"]})
    original_open = Image.open
    denied_once = False

    def open_with_temporary_denial(
        file: Path,
        mode: Literal["r"] = "r",
        formats: list[str] | tuple[str, ...] | None = None,
    ) -> Image.Image:
        nonlocal denied_once
        if Path(file) == image_path and not denied_once:
            denied_once = True
            raise PermissionError("file is temporarily locked")
        return original_open(file, mode=mode, formats=formats)

    monkeypatch.setattr(Image, "open", open_with_temporary_denial)

    assert run(config_path, recognizer) == 0
    assert denied_once
    assert (tmp_path / "ocr_results.csv").is_file()


def test_run_reports_corrupt_image_without_stopping_later_images(
    tmp_path: Path,
    pipeline_image_writer: Callable[[Path, int], Path],
) -> None:
    """A corrupt file is a terminal load failure, while later images still run."""
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    (image_dir / "alpha-corrupt.png").write_bytes(b"not a PNG image")
    pipeline_image_writer(image_dir / "beta-good.png", 2)
    config_path = _write_config(tmp_path, image_dir)
    recognizer = ScriptedRecognizer({2: ["recognized"]})

    assert run(config_path, recognizer) == 1

    with (tmp_path / "ocr_results.partial.csv").open(encoding="utf-8", newline="") as stream:
        partial_rows = list(csv.DictReader(stream))
    assert [(row["filename"], row["text"]) for row in partial_rows] == [
        ("beta-good.png", "recognized")
    ]
    with (tmp_path / "ocr_failures.csv").open(encoding="utf-8", newline="") as stream:
        failures = list(csv.DictReader(stream))
    assert len(failures) == 1
    failure = failures[0]
    assert {
        key: failure[key]
        for key in (
            "image_id",
            "filename",
            "stage",
            "attempts",
            "exception_type",
        )
    } == {
        "image_id": "1",
        "filename": "alpha-corrupt.png",
        "stage": "load",
        "attempts": "1",
        "exception_type": "UnidentifiedImageError",
    }
    assert failure["message"].startswith("cannot identify image file")


def test_run_treats_missing_ocr_prerequisite_as_global_error(
    tmp_path: Path,
    pipeline_image_writer: Callable[[Path, int], Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A shared prerequisite failure is reported globally and preserves complete output."""
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    pipeline_image_writer(image_dir / "alpha.png", 1)
    config_path = _write_config(tmp_path, image_dir)
    old_output = tmp_path / "ocr_results.csv"
    old_output.write_text("previous complete run\n", encoding="utf-8")
    recognizer = ScriptedRecognizer({1: [PrerequisiteError("model unavailable")]})

    assert run(config_path, recognizer) == 1

    assert old_output.read_text(encoding="utf-8") == "previous complete run\n"
    with (tmp_path / "ocr_results.partial.csv").open(encoding="utf-8", newline="") as stream:
        assert list(csv.reader(stream)) == [["image_id", "filename", "text", "processing_time_ms"]]
    with (tmp_path / "ocr_failures.csv").open(encoding="utf-8", newline="") as stream:
        failures = list(csv.DictReader(stream))
    assert failures[0]["stage"] == "pipeline"
    assert failures[0]["exception_type"] == "PrerequisiteError"
    assert failures[1]["filename"] == "alpha.png"
    assert failures[1]["stage"] == "unprocessed"
    assert "cancelled" not in failures[1]["message"]
    assert "model unavailable" in capsys.readouterr().err


def test_run_rolls_back_partial_artifact_if_failure_report_cannot_be_published(
    tmp_path: Path,
    pipeline_image_writer: Callable[[Path, int], Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed second artifact replacement restores both prior report files."""
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    pipeline_image_writer(image_dir / "alpha.png", 1)
    config_path = _write_config(tmp_path, image_dir)
    partial_path = tmp_path / "ocr_results.partial.csv"
    failures_path = tmp_path / "ocr_failures.csv"
    partial_path.write_text("old partial\n", encoding="utf-8")
    failures_path.write_text("old failures\n", encoding="utf-8")
    recognizer = ScriptedRecognizer({1: [RecognitionFailedError("terminal image failure")]})
    original_replace = os.replace
    fail_failure_publication = True

    def replace_with_failure(
        source: str | os.PathLike[str], destination: str | os.PathLike[str]
    ) -> None:
        nonlocal fail_failure_publication
        if Path(destination) == failures_path and fail_failure_publication:
            fail_failure_publication = False
            raise OSError("failure report destination is unavailable")
        original_replace(source, destination)

    monkeypatch.setattr(os, "replace", replace_with_failure)

    assert run(config_path, recognizer) == 1
    assert partial_path.read_text(encoding="utf-8") == "old partial\n"
    assert failures_path.read_text(encoding="utf-8") == "old failures\n"


def test_run_preserves_complete_output_and_publishes_partial_after_output_error(
    tmp_path: Path,
    pipeline_image_writer: Callable[[Path, int], Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed complete-output replacement leaves the prior CSV and reports this run."""
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    pipeline_image_writer(image_dir / "alpha.png", 1)
    config_path = _write_config(tmp_path, image_dir)
    complete_path = tmp_path / "ocr_results.csv"
    complete_path.write_text("previous complete run\n", encoding="utf-8")
    original_replace = os.replace

    def reject_complete_publication(
        source: str | os.PathLike[str], destination: str | os.PathLike[str]
    ) -> None:
        if Path(destination) == complete_path:
            raise OSError("complete output is read-only")
        original_replace(source, destination)

    monkeypatch.setattr(os, "replace", reject_complete_publication)

    assert run(config_path, ScriptedRecognizer({1: ["recognized"]})) == 1

    assert complete_path.read_text(encoding="utf-8") == "previous complete run\n"
    with (tmp_path / "ocr_results.partial.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert [(row["filename"], row["text"]) for row in rows] == [("alpha.png", "recognized")]
    with (tmp_path / "ocr_failures.csv").open(encoding="utf-8", newline="") as stream:
        failures = list(csv.DictReader(stream))
    assert failures[0]["stage"] == "pipeline"
    assert failures[0]["message"] == "complete output is read-only"


@pytest.mark.parametrize("stop_kind", ["cancellation", "worker_failure"])
def test_run_stops_with_a_full_queue_and_closes_queued_images(
    tmp_path: Path,
    pipeline_image_writer: Callable[[Path, int], Path],
    stop_kind: str,
) -> None:
    """Cancellation and global failure drain queued images under a subprocess timeout."""
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    for index in range(8):
        pipeline_image_writer(image_dir / f"{index:02}.png", index)
    _write_config(tmp_path, image_dir, n_workers=1)
    previous = tmp_path / "ocr_results.csv"
    previous.write_text("previous complete run\n", encoding="utf-8")
    script = textwrap.dedent(
        f"""
        import json
        import signal
        import threading
        from pathlib import Path
        from PIL import Image
        from parallel_ocr_pipeline.pipeline import run

        root = Path({str(tmp_path)!r})
        stop_kind = {stop_kind!r}
        previous = root / "ocr_results.csv"
        recognizer_started = threading.Event()
        release_recognizer = threading.Event()
        queue_full_observed = threading.Event()
        release_loader = threading.Event()
        detached_images = []
        worker_threads = []
        open_count = [0]
        open_lock = threading.Lock()
        original_open = Image.open
        original_copy = Image.Image.copy

        class SlowRecognizer:
            def recognize(self, image, /):
                worker_threads.append(threading.current_thread())
                recognizer_started.set()
                if not release_recognizer.wait(timeout=5):
                    raise TimeoutError("Test did not release the active recognition.")
                if stop_kind == "worker_failure":
                    raise KeyboardInterrupt("Synthetic worker entry failure.")
                return "recognized"

        def tracked_open(file, *args, **kwargs):
            source = original_open(file, *args, **kwargs)
            with open_lock:
                open_count[0] += 1
                current_open = open_count[0]
            if current_open == 2 and not recognizer_started.wait(timeout=5):
                raise TimeoutError("The first image never reached the recognizer.")
            if current_open == 4:
                # One image is active and the two-slot queue is full; the loader has begun
                # loading a fourth image and cannot enqueue it until shutdown is requested.
                queue_full_observed.set()
                if not release_loader.wait(timeout=5):
                    raise TimeoutError("Test did not release the blocked loader.")
            return source

        def tracked_copy(image):
            detached = original_copy(image)
            detached_images.append(detached)
            return detached

        def interrupt(signum, frame):
            release_loader.set()
            release_recognizer.set()
            raise KeyboardInterrupt

        Image.open = tracked_open
        Image.Image.copy = tracked_copy
        signal.signal(signal.SIGINT, interrupt)

        def cancel_when_queue_is_full():
            queue_full_observed.wait(timeout=5)
            if stop_kind == "cancellation":
                signal.raise_signal(signal.SIGINT)
            else:
                release_loader.set()
                release_recognizer.set()

        canceller = threading.Thread(target=cancel_when_queue_is_full)
        canceller.start()
        status = run(root / "config.txt", SlowRecognizer())
        canceller.join(timeout=5)
        detached_images_closed = True
        for image in detached_images:
            try:
                image.getpixel((0, 0))
                detached_images_closed = False
            except ValueError:
                pass
        worker_threads_joined = bool(worker_threads) and all(
            not thread.is_alive() for thread in worker_threads
        )
        print(json.dumps({{
            "status": status,
            "old_output": previous.read_text(encoding="utf-8"),
            "partial_exists": (root / "ocr_results.partial.csv").is_file(),
            "failure_exists": (root / "ocr_failures.csv").is_file(),
            "queue_full_observed": queue_full_observed.is_set(),
            "loaded_count": len(detached_images),
            "detached_images_closed": detached_images_closed,
            "worker_threads_joined": worker_threads_joined,
            "canceller_joined": not canceller.is_alive(),
        }}))
        """
    )

    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout.splitlines()[-1])
    assert result == {
        "status": 130 if stop_kind == "cancellation" else 1,
        "old_output": "previous complete run\n",
        "partial_exists": True,
        "failure_exists": True,
        "queue_full_observed": True,
        "loaded_count": 4,
        "detached_images_closed": True,
        "worker_threads_joined": True,
        "canceller_joined": True,
    }


@pytest.mark.parametrize("interrupt_at", ["start", "alive_check"])
def test_run_cancels_during_startup_without_losing_active_results_or_leaking_threads(
    tmp_path: Path,
    pipeline_image_writer: Callable[[Path, int], Path],
    interrupt_at: str,
) -> None:
    """An interrupted start still joins its thread before closing shared output."""
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    pipeline_image_writer(image_dir / "alpha.png", 1)
    pipeline_image_writer(image_dir / "beta.png", 2)
    _write_config(tmp_path, image_dir)
    (tmp_path / "ocr_results.csv").write_text("previous complete run\n", encoding="utf-8")
    script = textwrap.dedent(
        f"""
        import csv
        import json
        import threading
        from pathlib import Path
        from PIL import Image
        from parallel_ocr_pipeline.pipeline import run

        root = Path({str(tmp_path)!r})
        active = threading.Event()
        loading = threading.Event()
        release_recognizer = threading.Event()
        release_loader = threading.Event()
        started = []
        recognized_images = []
        original_start = threading.Thread.start
        original_join = threading.Thread.join
        original_is_alive = threading.Thread.is_alive
        original_open = Image.open
        interrupted = False

        class SlowRecognizer:
            def recognize(self, image, /):
                recognized_images.append(image)
                active.set()
                if not release_recognizer.wait(5):
                    raise TimeoutError("Active recognition was never joined.")
                return "recognized"

        def blocked_open(file, *args, **kwargs):
            if Path(file).name == "beta.png":
                loading.set()
                if not release_loader.wait(5):
                    raise TimeoutError("Active loader was never joined.")
            return original_open(file, *args, **kwargs)

        def interrupted_start(thread):
            original_start(thread)
            started.append(thread)
            if len(started) == 2:
                assert active.wait(5) and loading.wait(5)
                if {interrupt_at!r} == "start":
                    raise KeyboardInterrupt

        def interrupted_alive_check(thread):
            global interrupted
            if {interrupt_at!r} == "alive_check" and len(started) == 2 and not interrupted:
                interrupted = True
                raise KeyboardInterrupt
            return original_is_alive(thread)

        def releasing_join(thread, *args, **kwargs):
            # Hold active work until cleanup joins its owning OS thread.
            if thread is started[0]:
                release_recognizer.set()
            else:
                release_loader.set()
            return original_join(thread, *args, **kwargs)

        Image.open = blocked_open
        threading.Thread.start = interrupted_start
        threading.Thread.join = releasing_join
        threading.Thread.is_alive = interrupted_alive_check
        try:
            status = run(root / "config.txt", SlowRecognizer())
            joined = all(not thread.is_alive() for thread in started)
            images_closed = True
            for image in recognized_images:
                try:
                    image.getpixel((0, 0))
                    images_closed = False
                except ValueError:
                    pass
        finally:
            release_recognizer.set()
            release_loader.set()
            for thread in started:
                original_join(thread, timeout=5)
        with (root / "ocr_results.partial.csv").open(newline="", encoding="utf-8") as stream:
            partial = list(csv.DictReader(stream))
        with (root / "ocr_failures.csv").open(newline="", encoding="utf-8") as stream:
            failures = list(csv.DictReader(stream))
        print(json.dumps({{
            "status": status,
            "joined": joined,
            "images_closed": images_closed,
            "old_output": (root / "ocr_results.csv").read_text(encoding="utf-8"),
            "partial": [(row["filename"], row["text"]) for row in partial],
            "errors": [row["exception_type"] for row in failures],
        }}))
        """
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout.splitlines()[-1]) == {
        "status": 130,
        "joined": True,
        "images_closed": True,
        "old_output": "previous complete run\n",
        "partial": [["alpha.png", "recognized"]],
        "errors": ["KeyboardInterrupt", "NotProcessedError"],
    }


@pytest.mark.parametrize("failure_at", ["loader", "worker"])
def test_run_reports_unexpected_thread_entry_errors_and_joins_every_thread(
    tmp_path: Path,
    pipeline_image_writer: Callable[[Path, int], Path],
    failure_at: str,
) -> None:
    """Unexpected loader or worker BaseExceptions are reported and never leak threads."""
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    pipeline_image_writer(image_dir / "alpha.png", 1)
    _write_config(tmp_path, image_dir, n_workers=2)
    previous = tmp_path / "ocr_results.csv"
    previous.write_text("previous complete run\n", encoding="utf-8")
    script = textwrap.dedent(
        f"""
        import csv
        import json
        import threading
        from pathlib import Path
        from PIL import Image
        from parallel_ocr_pipeline.pipeline import run

        root = Path({str(tmp_path)!r})
        failure_at = {failure_at!r}
        existing_threads = {{thread.ident for thread in threading.enumerate()}}
        received_images = []

        class CrashingRecognizer:
            def recognize(self, image, /):
                received_images.append(image)
                raise KeyboardInterrupt("unexpected worker entry failure")

        if failure_at == "loader":
            def fail_to_open(*args, **kwargs):
                raise KeyboardInterrupt("unexpected loader entry failure")
            Image.open = fail_to_open

        status = run(root / "config.txt", CrashingRecognizer())
        with (root / "ocr_failures.csv").open(encoding="utf-8", newline="") as stream:
            failures = list(csv.DictReader(stream))
        pipeline_failures = [failure for failure in failures if failure["stage"] == "pipeline"]
        live_threads = [
            thread.name
            for thread in threading.enumerate()
            if thread.ident not in existing_threads
        ]
        images_closed = True
        for image in received_images:
            try:
                image.getpixel((0, 0))
                images_closed = False
            except ValueError:
                pass
        with (root / "ocr_results.partial.csv").open(encoding="utf-8", newline="") as stream:
            partial_rows = list(csv.DictReader(stream))
        print(json.dumps({{
            "status": status,
            "pipeline_failure_types": [failure["exception_type"] for failure in pipeline_failures],
            "live_threads": live_threads,
            "old_output": (root / "ocr_results.csv").read_text(encoding="utf-8"),
            "partial_rows": len(partial_rows),
            "received_images": len(received_images),
            "images_closed": images_closed,
        }}))
        """
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout.splitlines()[-1]) == {
        "status": 1,
        "pipeline_failure_types": ["KeyboardInterrupt"],
        "live_threads": [],
        "old_output": "previous complete run\n",
        "partial_rows": 0,
        "received_images": 1 if failure_at == "worker" else 0,
        "images_closed": True,
    }
