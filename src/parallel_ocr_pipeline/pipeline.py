"""Run images through one loader and a bounded pool of OCR workers."""

from __future__ import annotations

import csv
import os
import queue
import sys
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter_ns
from typing import TextIO

from PIL import Image

from parallel_ocr_pipeline.config import InputImage, enumerate_images, load_config
from parallel_ocr_pipeline.contracts import ImageRecognizer
from parallel_ocr_pipeline.recognizer import (
    PrerequisiteError,
    RecognitionError,
    RecognitionFailedError,
    RecognitionTimeoutError,
    TesseractRecognizer,
)


@dataclass(slots=True)
class _ImageJob:
    image_id: int
    filename: str
    image: Image.Image


@dataclass(frozen=True, slots=True)
class _ImageFailure:
    image_id: int | None
    filename: str
    stage: str
    attempts: int
    exception_type: str
    message: str


def run(config_path: str | Path, recognizer: ImageRecognizer | None = None) -> int:
    """Run the configured pipeline; return 0, 1, or 130 for success, failure, or cancellation."""
    config_file = Path(config_path).expanduser().resolve()
    config = load_config(config_file)
    inputs = enumerate_images(config.image_dir)
    chosen_recognizer = recognizer if recognizer is not None else TesseractRecognizer()
    output_path = config_file.parent / "ocr_results.csv"
    # Shared object queue
    jobs: queue.Queue[_ImageJob] = queue.Queue(maxsize=2 * config.n_workers)
    # threading lock
    output_lock = threading.Lock()
    # event to stop everything possibly due to an error
    stop_requested = threading.Event()
    fatal_errors: list[BaseException] = []
    successful_ids: set[int] = set()
    image_failures: list[_ImageFailure] = []
    cancelled = False

    def request_stop(error: BaseException | None = None) -> None:
        if error is not None:
            with output_lock:
                fatal_errors.append(error)
        stop_requested.set()
        jobs.shutdown()

    def stop_after(error: BaseException) -> None:
        with output_lock:
            fatal_errors.append(error)
        stop_requested.set()
        jobs.shutdown()

    def record_image_failure(
        image_id: int | None, filename: str, stage: str, attempts: int, error: BaseException
    ) -> None:
        with output_lock:
            image_failures.append(
                _ImageFailure(
                    image_id=image_id,
                    filename=filename,
                    stage=stage,
                    attempts=attempts,
                    exception_type=type(error).__name__,
                    message=str(error),
                )
            )

    def loader() -> None:
        try:
            for input_image in inputs:
                if stop_requested.is_set():
                    break
                image: Image.Image | None = None
                for attempt in range(1, 3):
                    if stop_requested.is_set():
                        break
                    try:
                        image = _load_image(input_image)
                        break
                    except PermissionError as error:
                        if attempt == 2 or stop_requested.is_set():
                            record_image_failure(
                                input_image.image_id,
                                input_image.path.name,
                                "load",
                                attempt,
                                error,
                            )
                    except (OSError, ValueError, Image.DecompressionBombError) as error:
                        record_image_failure(
                            input_image.image_id,
                            input_image.path.name,
                            "load",
                            attempt,
                            error,
                        )
                        break

                if image is None:
                    continue
                try:
                    jobs.put(
                        _ImageJob(
                            image_id=input_image.image_id,
                            filename=input_image.path.name,
                            image=image,
                        )
                    )
                except queue.ShutDown:
                    image.close()
                    if not stop_requested.is_set():
                        raise
                    break
                except Exception:
                    image.close()
                    raise
        except BaseException as error:  # noqa: BLE001
            stop_after(error)
        finally:
            jobs.shutdown()

    def worker(stream: TextIO) -> None:
        writer = csv.writer(stream)
        while True:
            try:
                job = jobs.get()
            except queue.ShutDown:
                return

            try:
                if stop_requested.is_set():
                    continue
                started_ns = perf_counter_ns()
                text = ""
                recognized = False
                for attempt in range(1, 3):
                    if stop_requested.is_set():
                        break
                    try:
                        text = chosen_recognizer.recognize(job.image)
                        recognized = True
                        break
                    except RecognitionTimeoutError as error:
                        if attempt == 2 or stop_requested.is_set():
                            record_image_failure(
                                job.image_id,
                                job.filename,
                                "recognize",
                                attempt,
                                error,
                            )
                    except RecognitionFailedError as error:
                        record_image_failure(
                            job.image_id,
                            job.filename,
                            "recognize",
                            attempt,
                            error,
                        )
                        break
                    except PrerequisiteError as error:
                        stop_after(error)
                        break
                    except RecognitionError as error:
                        record_image_failure(
                            job.image_id,
                            job.filename,
                            "recognize",
                            attempt,
                            error,
                        )
                        break

                if not recognized:
                    continue
                processing_time_ms = (perf_counter_ns() - started_ns) / 1_000_000
                with output_lock:
                    if job.image_id in successful_ids:
                        raise RuntimeError(f"Image ID {job.image_id} was processed more than once.")
                    writer.writerow(
                        [
                            job.image_id,
                            job.filename,
                            text,
                            f"{processing_time_ms:.3f}",
                        ]
                    )
                    successful_ids.add(job.image_id)
            except Exception as error:  # noqa: BLE001
                stop_after(error)
            finally:
                try:
                    job.image.close()
                except Exception as error:  # noqa: BLE001
                    stop_after(error)

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        print(f"Cannot create the output directory {output_path.parent}: {error}", file=sys.stderr)
        return 1
    temporary_path: Path | None = None
    loader_thread = threading.Thread(target=loader, daemon=False)
    started_threads: list[threading.Thread] = []
    workers: list[threading.Thread] = []
    cancelled = False
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            prefix=".ocr_results.",
            suffix=".tmp",
            dir=output_path.parent,
            delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
            csv.writer(stream).writerow(["image_id", "filename", "text", "processing_time_ms"])
            workers = [
                threading.Thread(
                    target=_worker_entry,
                    args=(worker, stream, stop_after),
                    daemon=False,
                )
                for _ in range(config.n_workers)
            ]
            for thread in [*workers, loader_thread]:
                thread.start()
                started_threads.append(thread)
            cancelled = _join_threads(started_threads, request_stop)
            stream.flush()
    except KeyboardInterrupt:
        cancelled = True
        request_stop()
        _join_threads(started_threads, request_stop)
    except BaseException as error:  # noqa: BLE001
        request_stop(error)
        _join_threads(started_threads, request_stop)
        print(
            f"Pipeline setup or output failed: {type(error).__name__}: {error}",
            file=sys.stderr,
        )

    _close_queued_images(jobs, stop_after)

    expected_ids = {input_image.image_id for input_image in inputs}
    failed_ids = [failure.image_id for failure in image_failures if failure.image_id is not None]
    outcome_ids = successful_ids | set(failed_ids)
    if (
        not fatal_errors
        and not cancelled
        and (
            outcome_ids != expected_ids
            or len(failed_ids) != len(set(failed_ids))
            or successful_ids.intersection(failed_ids)
        )
    ):
        request_stop(
            RuntimeError(
                "The OCR pipeline finished without exactly one outcome for every input image."
            )
        )

    if fatal_errors or cancelled or image_failures:
        global_error = fatal_errors[0] if fatal_errors else None
        report_failures = list(image_failures)
        for error in fatal_errors:
            report_failures.append(
                _ImageFailure(
                    image_id=None,
                    filename="",
                    stage="pipeline",
                    attempts=0,
                    exception_type=type(error).__name__,
                    message=str(error),
                ),
            )
        if cancelled:
            report_failures.insert(
                0,
                _ImageFailure(
                    image_id=None,
                    filename="",
                    stage="pipeline",
                    attempts=0,
                    exception_type="KeyboardInterrupt",
                    message="Run cancelled by user.",
                ),
            )
        reported_ids = {
            failure.image_id for failure in report_failures if failure.image_id is not None
        }
        if cancelled:
            reason = "Run cancelled before this image was processed."
        elif global_error is not None:
            reason = f"Pipeline stopped before this image was processed: {global_error}"
        else:
            reason = "Image was not processed because the run ended early."
        report_failures.extend(
            _ImageFailure(
                image_id=input_image.image_id,
                filename=input_image.path.name,
                stage="unprocessed",
                attempts=0,
                exception_type="NotProcessedError",
                message=reason,
            )
            for input_image in inputs
            if input_image.image_id not in successful_ids
            and input_image.image_id not in reported_ids
        )
        report_failures.sort(
            key=lambda failure: (
                failure.image_id is not None,
                failure.image_id if failure.image_id is not None else 0,
            )
        )

        failure_temporary_path: Path | None = None
        try:
            if temporary_path is None or not temporary_path.exists():
                temporary_path = _write_results_header(output_path.parent)
            failure_temporary_path = _write_failure_report(output_path.parent, report_failures)
            _publish_report_pair(
                temporary_path,
                failure_temporary_path,
                config_file.parent / "ocr_results.partial.csv",
                config_file.parent / "ocr_failures.csv",
            )
            temporary_path = None
            failure_temporary_path = None
        except OSError as error:
            print(
                f"Could not publish partial results and failure report: {error}. "
                "Any existing report files were preserved where possible.",
                file=sys.stderr,
            )
        finally:
            _remove_temporary_file(temporary_path)
            temporary_path = None
            if failure_temporary_path is not None:
                _remove_temporary_file(failure_temporary_path)

        if global_error is not None:
            print(
                f"Pipeline stopped: {type(global_error).__name__}: {global_error}. "
                f"Completed {len(successful_ids)} of {len(inputs)} images.",
                file=sys.stderr,
            )
        elif cancelled:
            print(
                f"Pipeline cancelled. Completed {len(successful_ids)} of {len(inputs)} images.",
                file=sys.stderr,
            )
        else:
            print(
                f"Processed {len(successful_ids)} of {len(inputs)} images; "
                f"{len(image_failures)} image(s) failed. Any existing ocr_results.csv is "
                "from a previous successful run.",
                file=sys.stderr,
            )
        return 130 if cancelled else 1

    try:
        if temporary_path is None:
            raise RuntimeError("The completed output temporary file is missing.")
        os.replace(temporary_path, output_path)
    except OSError as error:
        output_error_report_path: Path | None = None
        try:
            if temporary_path is None or not temporary_path.exists():
                temporary_path = _write_results_header(output_path.parent)
            output_error_report_path = _write_failure_report(
                output_path.parent,
                [
                    _ImageFailure(
                        image_id=None,
                        filename="",
                        stage="pipeline",
                        attempts=0,
                        exception_type=type(error).__name__,
                        message=str(error),
                    )
                ],
            )
            _publish_report_pair(
                temporary_path,
                output_error_report_path,
                config_file.parent / "ocr_results.partial.csv",
                config_file.parent / "ocr_failures.csv",
            )
            temporary_path = None
            output_error_report_path = None
        except OSError as publish_error:
            print(
                f"Could not publish complete results: {error}. "
                f"Could not publish partial reports either: {publish_error}.",
                file=sys.stderr,
            )
        finally:
            _remove_temporary_file(temporary_path)
            if output_error_report_path is not None:
                _remove_temporary_file(output_error_report_path)
        if temporary_path is None:
            print(
                f"Could not publish complete OCR results: {error}. "
                "Partial results and an error report were written instead.",
                file=sys.stderr,
            )
        return 1
    temporary_path = None
    stale_artifact_errors: list[OSError] = []
    for artifact in (
        config_file.parent / "ocr_results.partial.csv",
        config_file.parent / "ocr_failures.csv",
    ):
        try:
            artifact.unlink(missing_ok=True)
        except OSError as error:
            stale_artifact_errors.append(error)
    if stale_artifact_errors:
        message = "; ".join(str(error) for error in stale_artifact_errors)
        print(
            "Complete results were published, but stale partial artifacts could not be removed: "
            f"{message}",
            file=sys.stderr,
        )
        return 1
    return 0


def _worker_entry(
    worker: Callable[[TextIO], None],
    stream: TextIO,
    stop_after: Callable[[BaseException], None],
) -> None:
    try:
        worker(stream)
    except BaseException as error:  # noqa: BLE001
        stop_after(error)


def _join_threads(threads: list[threading.Thread], on_interrupt: Callable[[], None]) -> bool:
    interrupted = False
    for thread in threads:
        while thread.is_alive():
            try:
                thread.join(timeout=0.1)
            except KeyboardInterrupt:
                interrupted = True
                on_interrupt()
    return interrupted


def _close_queued_images(
    jobs: queue.Queue[_ImageJob], stop_after: Callable[[BaseException], None]
) -> None:
    while True:
        try:
            job = jobs.get_nowait()
        except queue.Empty, queue.ShutDown:
            return
        try:
            job.image.close()
        except BaseException as error:  # noqa: BLE001
            stop_after(error)


def _write_results_header(directory: Path) -> Path:
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="",
        prefix=".ocr_results.",
        suffix=".tmp",
        dir=directory,
        delete=False,
    ) as stream:
        path = Path(stream.name)
        csv.writer(stream).writerow(["image_id", "filename", "text", "processing_time_ms"])
    return path


def _write_failure_report(directory: Path, failures: list[_ImageFailure]) -> Path:
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="",
        prefix=".ocr_failures.",
        suffix=".tmp",
        dir=directory,
        delete=False,
    ) as stream:
        path = Path(stream.name)
        writer = csv.writer(stream)
        writer.writerow(["image_id", "filename", "stage", "attempts", "exception_type", "message"])
        for failure in failures:
            writer.writerow(
                [
                    failure.image_id if failure.image_id is not None else "",
                    failure.filename,
                    failure.stage,
                    failure.attempts,
                    failure.exception_type,
                    failure.message,
                ]
            )
    return path


def _publish_report_pair(
    partial_temporary: Path,
    failure_temporary: Path,
    partial_path: Path,
    failure_path: Path,
) -> None:
    destinations = (partial_path, failure_path)
    sources = (partial_temporary, failure_temporary)
    backups: dict[Path, Path] = {}
    published: list[Path] = []
    try:
        for destination in destinations:
            if destination.exists():
                with tempfile.NamedTemporaryFile(
                    prefix=f".{destination.name}.backup.",
                    suffix=".tmp",
                    dir=destination.parent,
                    delete=False,
                ) as backup_stream:
                    backup = Path(backup_stream.name)
                backup.unlink()
                os.replace(destination, backup)
                backups[destination] = backup

        for source, destination in zip(sources, destinations, strict=True):
            os.replace(source, destination)
            published.append(destination)
    except OSError as error:
        rollback_errors: list[OSError] = []
        for destination in reversed(published):
            try:
                destination.unlink(missing_ok=True)
            except OSError as rollback_error:
                rollback_errors.append(rollback_error)
        for destination, backup in reversed(tuple(backups.items())):
            try:
                if backup.exists():
                    os.replace(backup, destination)
            except OSError as rollback_error:
                rollback_errors.append(rollback_error)
        if rollback_errors:
            details = "; ".join(str(rollback_error) for rollback_error in rollback_errors)
            retained = ", ".join(str(path) for path in backups.values() if path.exists())
            raise OSError(
                f"{error}; artifact rollback also failed: {details}; preserved backups: {retained}"
            ) from error
        raise
    for backup in backups.values():
        _remove_temporary_file(backup)


def _remove_temporary_file(path: Path | None) -> None:
    if path is not None:
        try:
            path.unlink(missing_ok=True)
        except OSError as error:
            print(f"Could not remove temporary file {path}: {error}", file=sys.stderr)


def _load_image(input_image: InputImage) -> Image.Image:
    """Load and detach image pixels before handing ownership to the queue."""
    with Image.open(input_image.path) as source:
        source.load()
        image = source.copy()
        try:
            image.load()
        except BaseException:
            image.close()
            raise
    return image
