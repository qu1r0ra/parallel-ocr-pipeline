# Integrated OCR validation

This record covers the local evidence for [issue #6](https://github.com/qu1r0ra/parallel-ocr-pipeline/issues/6). The project owner completed this acceptance on their Windows machine. Per the project decision, a second-host run is optional follow-up and does not block issue #6. The timings below are single acceptance runs, not benchmark measurements for #7.

## Local environment

| Item | Value |
|---|---|
| Operating system | Windows 11, build 26300 |
| CPU | AMD Ryzen 5 5600X, 6 cores / 12 threads |
| Python | 3.15.0 |
| uv | 0.13.5 |
| just | 1.59.0 |
| Pillow | 12.3.0 |
| pytesseract | 0.3.13 |
| Tesseract | 5.4.0.20240606 |
| Dataset and model | 100 prepared images, supplied English model |
| Native OCR threads | `OMP_THREAD_LIMIT=1` for the compared runs |

`uv sync --locked --all-groups` and `just check-environment` passed. The environment check imported Pillow and pytesseract, found the supplied model and all 100 images, and ran Tesseract with that model.

## Recognition quality

The evaluator uses NFKC normalization, casefolding, and letters/digits only. It computes micro character accuracy as `1 − total Levenshtein distance ÷ total expected characters`; the required threshold is 0.5. Labels are used only after recognition for scoring.

| Run | Workers | Rows | Exact matches | Character accuracy | Recognition failures | Full-run output |
|---|---:|---:|---:|---:|---:|---:|
| Standalone `just evaluate` | — | 100 images | 96 | 0.9952 | 0 | Threshold passed |
| Pipeline CSV | 1 | 100 | 96 | 0.9952 | 0 | 14.333 s |
| Pipeline CSV | 4 | 100 | 96 | 0.9952 | 0 | 4.415 s |

The pipeline rows were checked for unique filenames, IDs associated with the sorted filenames, finite nonnegative per-image times, and the same character score as standalone evaluation. The 1-worker and 4-worker pipeline CSVs both pass `just evaluate-pipeline`. The four recognition mismatches are `fireproof`→`fireprocof`, `elision`→`clision`, `rotan`→`fotan`, and `boraginaceae`→`boraginacéae`.

These local pipeline runs match the standalone score. The [ticket #7 benchmark report](benchmark-results.md) records separate throughput measurements on this host and keeps the older results from a different host and Tesseract version as historical context. Those older results are not cross-machine integrated validation. A second-host run was waived for issue #6 and remains optional follow-up.

## Lifecycle and shutdown evidence

| Concern | Check |
|---|---|
| Retry uses the same detached image and closes it afterward | `test_run_retries_timed_out_recognition_and_accepts_empty_text` asserts both recognition attempts receive the same detached image object and the worker closes it after completion. |
| Cancellation with a full queue | `test_run_stops_with_a_full_queue_and_closes_queued_images[cancellation]` verifies the active and queued images are closed, workers join, partial artifacts are published, and prior successful output is preserved. |
| Global worker failure with a full queue | `test_run_stops_with_a_full_queue_and_closes_queued_images[worker_failure]` injects an unexpected `KeyboardInterrupt` from recognition and verifies queued images close and workers join. |
| Loader and worker entry failures | `test_run_reports_unexpected_thread_entry_errors_and_joins_every_thread` checks failures are recorded, no live threads remain, and prior successful output is preserved. |
| Interrupt during thread startup or join checks | `test_run_cancels_during_startup_without_losing_active_results_or_leaking_threads` covers both interruption points and verifies completed rows and cleanup. |

Hang-sensitive shutdown cases run in subprocesses with 15-second limits. The OCR timeout bounds Tesseract calls; it does not bound arbitrary filesystem operations or an injected recognizer.

## Reproduce the check

To reproduce these results on another Windows host, install the locked environment and verify the local prerequisites:

```powershell
uv sync --locked --all-groups
just check-environment
just verify
$env:OMP_THREAD_LIMIT = '1'
just evaluate
```

Create separate output directories for one and multiple workers. Each config file contains the absolute dataset image directory and the requested worker count. This PowerShell block writes the configs as UTF-8 without a byte-order mark:

```powershell
$images = (Resolve-Path 'local-assets/dataset/images').Path
foreach ($workers in @(1, 4)) {
    $runDir = Join-Path 'results/integration' "workers-$workers"
    $null = New-Item -ItemType Directory -Path $runDir -Force
    $configPath = Join-Path $runDir 'config.txt'
    $config = "image_dir=$images`nn_workers=$workers`n"
    [System.IO.File]::WriteAllText(
        $configPath,
        $config,
        [System.Text.UTF8Encoding]::new($false)
    )
}
```

Run and score each complete CSV:

```powershell
$env:OMP_THREAD_LIMIT = '1'
just pipeline results/integration/workers-1/config.txt
just evaluate-pipeline results/integration/workers-1/ocr_results.csv
just pipeline results/integration/workers-4/config.txt
just evaluate-pipeline results/integration/workers-4/ocr_results.csv
```

Keep each config in its own directory because the pipeline writes output beside the config. Record Windows, Python, Pillow, pytesseract, and Tesseract versions, both standalone and pipeline accuracy/exact-match results, and any setup limitations. For optional cross-machine comparison, share the output with the other teammate. No course submission is performed by these checks.
