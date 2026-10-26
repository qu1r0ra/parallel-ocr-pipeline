"""Compare full-run OCR timings for one, two, and four workers."""

from __future__ import annotations

import csv
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

from parallel_ocr_pipeline.config import ConfigError, enumerate_images, load_config

WORKER_COUNTS = (1, 2, 4)
WARMUP_RUNS = 1
MEASURED_RUNS = 10
EXPECTED_IMAGE_COUNT = 100
_TOTAL_TIME = re.compile(r"^Total processing time: ([0-9]+\.[0-9]{3}) seconds$", re.MULTILINE)
_PIPELINE_SCRIPT = Path(__file__).with_name("run_pipeline.py")


class BenchmarkError(RuntimeError):
    """A benchmark run did not produce complete, measurable output."""


def main() -> int:
    config_path = Path("config.txt").resolve()
    try:
        config = load_config(config_path)
        inputs = enumerate_images(config.image_dir)
    except ConfigError as error:
        print(f"Cannot start benchmark: {error}", file=sys.stderr)
        return 2

    if len(inputs) != EXPECTED_IMAGE_COUNT:
        print(
            f"Cannot benchmark: expected {EXPECTED_IMAGE_COUNT} images, found {len(inputs)} "
            f"in {config.image_dir}.",
            file=sys.stderr,
        )
        return 2

    temporary_directory = Path(tempfile.mkdtemp(prefix="parallel-ocr-benchmark-"))
    try:
        durations = _run_benchmark(config.image_dir, temporary_directory, len(inputs))
    except BenchmarkError as error:
        print(f"Benchmark stopped: {error}.", file=sys.stderr)
        print(f"Temporary artifacts preserved at: {temporary_directory}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Benchmark interrupted.", file=sys.stderr)
        print(f"Temporary artifacts preserved at: {temporary_directory}", file=sys.stderr)
        return 130
    except OSError as error:
        print(f"Benchmark could not complete: {error}.", file=sys.stderr)
        print(f"Temporary artifacts preserved at: {temporary_directory}", file=sys.stderr)
        return 1

    _print_summary(durations)
    try:
        shutil.rmtree(temporary_directory)
    except OSError as error:
        print(
            f"Benchmark completed, but temporary outputs could not be removed from "
            f"{temporary_directory}: {error}",
            file=sys.stderr,
        )
        return 1
    return 0


def _run_benchmark(
    image_dir: Path, temporary_directory: Path, expected_image_count: int
) -> dict[int, list[float]]:
    environment = os.environ.copy()
    environment["OMP_THREAD_LIMIT"] = "1"
    durations = {worker_count: [] for worker_count in WORKER_COUNTS}

    for worker_count in WORKER_COUNTS:
        _run_once(
            image_dir,
            worker_count,
            "warmup",
            1,
            temporary_directory,
            expected_image_count,
            environment,
        )

    for trial in range(1, MEASURED_RUNS + 1):
        for worker_count in WORKER_COUNTS:
            duration = _run_once(
                image_dir,
                worker_count,
                "measured",
                trial,
                temporary_directory,
                expected_image_count,
                environment,
            )
            durations[worker_count].append(duration)
            print(
                f"Completed measured trial {trial}/{MEASURED_RUNS} "
                f"with {worker_count} worker(s): {duration:.3f} seconds."
            )
    return durations


def _run_once(
    image_dir: Path,
    worker_count: int,
    trial_kind: str,
    trial_number: int,
    temporary_directory: Path,
    expected_image_count: int,
    environment: dict[str, str],
) -> float:
    run_directory = temporary_directory / f"{trial_kind}-{trial_number:02}-workers-{worker_count}"
    run_directory.mkdir()
    config_path = run_directory / "config.txt"
    config_path.write_text(
        f"image_dir={image_dir}\nn_workers={worker_count}\n",
        encoding="utf-8",
    )
    try:
        completed = subprocess.run(
            [sys.executable, str(_PIPELINE_SCRIPT), str(config_path)],
            capture_output=True,
            cwd=Path.cwd(),
            env=environment,
            text=True,
            check=False,
        )
    except OSError as error:
        raise BenchmarkError(f"could not launch the pipeline: {error}") from error

    if completed.returncode != 0:
        (run_directory / "pipeline.stdout.txt").write_text(completed.stdout, encoding="utf-8")
        (run_directory / "pipeline.stderr.txt").write_text(completed.stderr, encoding="utf-8")
        raise BenchmarkError(
            f"{trial_kind} run {trial_number} with {worker_count} worker(s) exited "
            f"{completed.returncode}; see {run_directory}"
        )

    output_path = run_directory / "ocr_results.csv"
    try:
        with output_path.open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
    except OSError as error:
        raise BenchmarkError(f"could not read {output_path}: {error}") from error
    image_ids = [row["image_id"] for row in rows]
    if len(rows) != expected_image_count or len(set(image_ids)) != expected_image_count:
        raise BenchmarkError(
            f"{trial_kind} run {trial_number} with {worker_count} worker(s) produced "
            f"{len(rows)} rows and {len(set(image_ids))} unique IDs; expected "
            f"{expected_image_count} of each. See {run_directory}"
        )

    time_matches = _TOTAL_TIME.findall(completed.stdout)
    if len(time_matches) != 1:
        raise BenchmarkError(
            f"{trial_kind} run {trial_number} with {worker_count} worker(s) did not report "
            f"exactly one total processing time. See {run_directory}"
        )
    return float(time_matches[0])


def _print_summary(durations: dict[int, list[float]]) -> None:
    medians = {
        worker_count: statistics.median(worker_durations)
        for worker_count, worker_durations in durations.items()
    }
    baseline = medians[1]
    print(f"\nOMP_THREAD_LIMIT=1; measured runs per worker count: {MEASURED_RUNS}")
    for worker_count in WORKER_COUNTS:
        worker_durations = durations[worker_count]
        median = medians[worker_count]
        print(f"\nWorkers: {worker_count}")
        print(
            "Total processing times (seconds): "
            + ", ".join(f"{time:.3f}" for time in worker_durations)
        )
        print(
            f"Median total processing time: {median:.3f} seconds; "
            f"range: {min(worker_durations):.3f}-{max(worker_durations):.3f} seconds; "
            f"speedup: {baseline / median:.3f}x"
        )
    if not any(medians[count] < baseline for count in WORKER_COUNTS if count != 1):
        print(
            "\nNo multi-worker median was faster than the one-worker median; "
            "the performance-gain criterion is unmet."
        )


if __name__ == "__main__":
    raise SystemExit(main())
