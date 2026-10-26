"""Run images through one loader and a bounded pool of OCR workers."""

from __future__ import annotations

import csv
import os
import queue
import sys
import tempfile
import threading
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
    image_id: int
    filename: str
    stage: str
    attempts: int
    exception_type: str
    message: str


def run(config_path: str | Path, recognizer: ImageRecognizer | None = None) -> int:
    """Process configured images and publish a CSV beside the config file."""
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
    fatal_errors: list[Exception] = []
    successful_ids: set[int] = set()
    image_failures: list[_ImageFailure] = []

    def stop_after(error: Exception) -> None:
        with output_lock:
            fatal_errors.append(error)
        stop_requested.set()
        jobs.shutdown()

    def record_image_failure(
        image_id: int, filename: str, stage: str, attempts: int, error: Exception
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
        except Exception as error:  # noqa: BLE001
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

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
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

            # Initialize workers
            workers = [
                threading.Thread(target=worker, args=(stream,), daemon=False)
                for _ in range(config.n_workers)
            ]
            loader_thread = threading.Thread(target=loader, daemon=False)
            # Start worker threads
            for thread in [*workers, loader_thread]:
                thread.start()
            for thread in [*workers, loader_thread]:
                thread.join()

            if fatal_errors:
                raise RuntimeError("The OCR pipeline stopped after an unexpected error.") from (
                    fatal_errors[0]
                )
            expected_ids = {input_image.image_id for input_image in inputs}
            failed_ids = [failure.image_id for failure in image_failures]
            outcome_ids = successful_ids | set(failed_ids)
            if (
                outcome_ids != expected_ids
                or len(failed_ids) != len(set(failed_ids))
                or successful_ids.intersection(failed_ids)
            ):
                raise RuntimeError(
                    "The OCR pipeline finished without exactly one outcome for every input image."
                )

        if image_failures:
            partial_path = config_file.parent / "ocr_results.partial.csv"
            failure_path = config_file.parent / "ocr_failures.csv"
            failure_temporary_path: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    newline="",
                    prefix=".ocr_failures.",
                    suffix=".tmp",
                    dir=failure_path.parent,
                    delete=False,
                ) as failure_stream:
                    failure_temporary_path = Path(failure_stream.name)
                    failure_writer = csv.writer(failure_stream)
                    failure_writer.writerow(
                        [
                            "image_id",
                            "filename",
                            "stage",
                            "attempts",
                            "exception_type",
                            "message",
                        ]
                    )
                    for failure in image_failures:
                        failure_writer.writerow(
                            [
                                failure.image_id,
                                failure.filename,
                                failure.stage,
                                failure.attempts,
                                failure.exception_type,
                                failure.message,
                            ]
                        )
                os.replace(temporary_path, partial_path)
                temporary_path = None
                os.replace(failure_temporary_path, failure_path)
                failure_temporary_path = None
            finally:
                if failure_temporary_path is not None:
                    failure_temporary_path.unlink(missing_ok=True)
            print(
                f"Processed {len(successful_ids)} of {len(inputs)} images; "
                f"{len(image_failures)} image(s) failed. Any existing ocr_results.csv is "
                "from a previous successful run.",
                file=sys.stderr,
            )
            return 1

        os.replace(temporary_path, output_path)
        temporary_path = None
        return 0
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _load_image(input_image: InputImage) -> Image.Image:
    """Load and detach image pixels before handing ownership to the queue."""
    with Image.open(input_image.path) as source:
        source.load()
        image = source.copy()
        image.load()
    return image
