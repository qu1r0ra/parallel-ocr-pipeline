# M6 acceptance and benchmark results

**Status:** Local M6 evidence recorded; collaborator-machine verification remains pending.

This document maps [issue #5](https://github.com/qu1r0ra/parallel-ocr-pipeline/issues/5) to executable evidence and records machine-specific measurements. Performance results apply only to the machine listed below; the collaborator's machine still needs its own environment and real-OCR verification.

## Acceptance evidence

| Issue #5 criterion | Evidence | Status |
|---|---|---|
| Python 3.15 setup, locked tooling, and Windows environment | `just verify`; `just check-environment` on this host. The collaborator must repeat environment and real-OCR checks on their machine. | Local pass; collaborator pending |
| Config validation, empty input handling, relative paths, image filtering, and stable IDs | `tests/test_config.py`; `tests/test_cli.py::test_cli_reports_invalid_config_with_status_two` | Pass |
| One loader, bounded queue, and configured non-daemon OCR workers | `tests/test_pipeline.py::test_run_writes_associated_csv_rows_and_closes_images_and_threads`; implementation in `src/parallel_ocr_pipeline/pipeline.py` | Pass |
| Locked CSV output, identity association, escaping, and per-image timing | `tests/test_pipeline.py::test_run_writes_associated_csv_rows_and_closes_images_and_threads` | Pass |
| One retry for known transient load and OCR errors | `tests/test_pipeline.py::test_run_retries_timed_out_recognition_and_accepts_empty_text`; `tests/test_pipeline.py::test_run_retries_temporary_image_access_denial` | Pass |
| Terminal image failures, continued work, and failure details | `tests/test_pipeline.py::test_run_reports_image_failures_and_continues_other_images`; `tests/test_pipeline.py::test_run_reports_corrupt_image_without_stopping_later_images` | Pass |
| Complete/partial publication, rollback, and prior-output preservation | `tests/test_pipeline.py::test_run_rolls_back_partial_artifact_if_failure_report_cannot_be_published`; `tests/test_pipeline.py::test_run_preserves_complete_output_and_publishes_partial_after_output_error` | Pass |
| Global failure, cancellation, image cleanup, and thread termination | `tests/test_pipeline.py::test_run_treats_missing_ocr_prerequisite_as_global_error`; `tests/test_pipeline.py::test_run_publishes_only_partial_artifacts_when_interrupted` | Partial: cancellation test uses a timed interrupt and does not assert the queue is full |
| Deterministic behavior independent of OCR accuracy and speed | `just test tests/test_config.py`; `just test tests/test_pipeline.py`; `just test tests/test_cli.py` | Pass after final verification |
| Full-run timing and comparable worker-count performance | `tests/test_pipeline.py::test_run_reports_total_processing_time_after_publication`; `just benchmark`; results below | Local pass |
| Invocation, shared-state behavior, error outcomes, and benchmark method documented | `README.md`; `docs/concurrency-design.md`; this evidence record | Pass |

## Test and environment checks

Final M6 checks:

| Check | Result |
|---|---|
| `just verify` | Passed: 56 tests, Ruff, formatting, basedpyright, import, and lock checks |
| `just check-environment` | Passed: Python 3.15.0, Pillow, pytesseract, Tesseract/model, and 100 prepared images |
| `just evaluate` | Passed: 0.9928 character accuracy, 94 exact matches, 0 recognition failures (threshold 0.50) |
| Deterministic suite | Passed as part of `just verify`; independent of OCR accuracy/speed thresholds |

## Benchmark method

- Read `image_dir` from the root `config.txt`; use the full 100-image dataset. The runner overrides `n_workers` and does not edit the config.
- Compare 1, 2, and 4 OCR workers. Each count includes one unmeasured warm-up, followed by ten measured runs in interleaved worker-count order.
- Set `OMP_THREAD_LIMIT=1` only in the benchmark child processes. It limits native Tesseract/OpenMP threads, not the Python pipeline worker count.
- Each warm-up and measured run must succeed and produce 100 rows with unique IDs. OCR text is not compared across separate real runs; deterministic tests cover association and output behavior.
- Stop the whole benchmark on the first failed/incomplete run and preserve its temporary artifacts. Successful temporary outputs are deleted.
- Total duration starts immediately before thread startup/loading and ends after joins, stream close, and result publication. Configuration validation and image enumeration are excluded. Do not use the sum of per-image CSV timings as total elapsed time.
- For each worker count, report all ten durations, the median, and the min–max range. Calculate speedup as `median(1 worker) / median(n workers)`.
- If neither multi-worker median is lower than the one-worker median, report the performance-gain criterion as unmet.
- Run `just evaluate` separately and report its character accuracy and exact-match count independently of throughput.

## Machine and software

| Item | Value |
|---|---|
| Operating system | Windows 10 Home Single Language, version 25H2, build 26200.8457 |
| CPU | Intel Core i3-10110U @ 2.10 GHz; 4 logical processors |
| Project Python | 3.15.0 (`uv run --no-sync python --version`) |
| Tesseract | 5.5.3.20260724 |
| Dataset | 100 prepared images |
| Native OCR thread limit | `OMP_THREAD_LIMIT=1` for benchmark subprocesses |

## Measurements

Raw durations are in trial order; warm-ups are excluded.

| Workers | Ten total runtimes (seconds) | Median (seconds) | Range (seconds) | Speedup |
|---:|---|---:|---:|---:|
| 1 | 24.154, 26.211, 25.797, 26.758, 26.154, 25.837, 59.732, 31.309, 35.180, 26.274 | 26.242 | 24.154–59.732 | 1.000x |
| 2 | 17.239, 17.556, 17.229, 17.596, 17.004, 17.062, 20.289, 15.981, 15.976, 15.760 | 17.145 | 15.760–20.289 | 1.531x |
| 4 | 14.030, 13.865, 14.038, 13.975, 14.040, 32.084, 24.196, 13.206, 13.362, 14.232 | 14.034 | 13.206–32.084 | 1.870x |

The benchmark completed three unmeasured warm-ups and all 30 measured runs successfully. It checked 100 rows and unique IDs for every output, then removed all successful temporary outputs. It set `OMP_THREAD_LIMIT=1` only in the benchmark child processes.

**Performance conclusion:** Both multi-worker medians were faster than the one-worker median. The measured median speedups were 1.531x with 2 workers and 1.870x with 4 workers. The broad ranges, including several slower outliers, are retained above; these are machine-specific results, not a guarantee of speedup on another host.

**OCR quality (`just evaluate`):** 0.9928 character accuracy, 94 exact matches, and no recognition failures across 100 images.

**Cross-machine verification:** Pending collaborator run; this document does not claim results for the collaborator's machine.
