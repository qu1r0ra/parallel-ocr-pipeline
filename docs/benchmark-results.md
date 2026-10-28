# Ticket #7 benchmark results

**Status:** Quirora's repeated benchmark and complete CSV are recorded. Imman's review of the final artifacts remains pending.

This record covers the local issue #7 evidence. The performance results apply to the machine and software versions listed below. The coursework submission is a human action.

## Benchmark method

- Use all 100 prepared images and the supplied `eng.traineddata` model. The model SHA-256 is `7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2`.
- Compare 1, 2, and 4 Python OCR workers. Run one warm-up per worker count, then ten measured trials per count in interleaved order.
- Pin `OMP_THREAD_LIMIT=1` in each benchmark subprocess. The pipeline worker count controls Python-level concurrency; each Tesseract process uses one native OCR thread.
- Keep the dataset, model, preprocessing, 30-second per-attempt OCR timeout, retry policy, and output path behavior constant for the sweep.
- Require every warm-up and measurement to exit successfully and produce 100 rows with 100 unique image IDs. The benchmark stops at the first failed run and preserves its diagnostic output.
- The pipeline timer starts immediately before thread startup and includes loading, retry attempts, queue coordination, OCR, output locking, thread joins, stream close, and result publication. Configuration parsing and image enumeration happen before timing.
- Record each run's full duration and successful loader and recognizer retry counts. Failed or incomplete runs do not enter the speedup calculation.
- Calculate each worker count's median and range. Speedup is the one-worker median divided by the corresponding multi-worker median.

The raw terminal capture is in the local ignored file `results/issue7/benchmark-output.txt`. The run-level measurements are transcribed below so the repository report carries the evidence independently of that local file.

## Machine and software

| Item | Value |
|---|---|
| Run date | October 26, 2026 |
| Operating system | Windows 11 Pro, build 26300 |
| CPU | AMD Ryzen 5 5600X, 6 cores / 12 logical processors |
| Python | 3.15.0 |
| Pillow | 12.3.0 |
| pytesseract | 0.3.13 |
| Tesseract | 5.4.0.20240606 |
| uv / just | 0.13.5 / 1.59.0 |
| Dataset and model | 100 prepared images; supplied English `eng.traineddata` |
| Native OCR thread limit | `OMP_THREAD_LIMIT=1` in every benchmark subprocess |
| Successful retries | 0 loader retries and 0 recognizer retries in each warm-up and measured run |

## Warm-up runs

Warm-ups are excluded from the measured statistics.

| Workers | Elapsed time | Loader retries | Recognizer retries |
|---:|---:|---:|---:|
| 1 | 20.185 s | 0 | 0 |
| 2 | 6.964 s | 0 | 0 |
| 4 | 3.803 s | 0 | 0 |

## Raw measured runs

Each retry cell is `loader / recognizer` successful retries.

| Trial | 1 worker (s) | Retries | 2 workers (s) | Retries | 4 workers (s) | Retries |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 12.881 | 0 / 0 | 6.846 | 0 / 0 | 3.944 | 0 / 0 |
| 2 | 12.968 | 0 / 0 | 6.858 | 0 / 0 | 4.048 | 0 / 0 |
| 3 | 13.662 | 0 / 0 | 6.933 | 0 / 0 | 4.053 | 0 / 0 |
| 4 | 13.529 | 0 / 0 | 6.839 | 0 / 0 | 3.837 | 0 / 0 |
| 5 | 13.018 | 0 / 0 | 7.082 | 0 / 0 | 4.033 | 0 / 0 |
| 6 | 13.095 | 0 / 0 | 6.934 | 0 / 0 | 4.196 | 0 / 0 |
| 7 | 13.071 | 0 / 0 | 7.272 | 0 / 0 | 4.433 | 0 / 0 |
| 8 | 22.628 | 0 / 0 | 7.678 | 0 / 0 | 4.588 | 0 / 0 |
| 9 | 13.554 | 0 / 0 | 7.395 | 0 / 0 | 4.322 | 0 / 0 |
| 10 | 13.581 | 0 / 0 | 8.399 | 0 / 0 | 6.716 | 0 / 0 |

## Summary and analysis

| Workers | Median (s) | Range (s) | Speedup vs. 1 worker |
|---:|---:|---:|---:|
| 1 | 13.312 | 12.881–22.628 | 1.000x |
| 2 | 7.008 | 6.839–8.399 | 1.900x |
| 4 | 4.124 | 3.837–6.716 | 3.228x |

Four workers were the fastest measured configuration. The four-worker median was 3.228 times faster than the one-worker median and about 41% faster than the two-worker median. Both multi-worker medians beat the baseline, so the performance-gain criterion is met on this host.

Trial 8 at one worker and trial 10 at four workers were slower than their respective medians. The ranges preserve those runs. The measurements do not establish why those outliers occurred; the benchmark did not profile operating-system scheduling, storage, or Tesseract startup separately.

Parallel OCR reduced full-run time substantially while each Tesseract process was limited to one native thread. The remaining time at four workers includes image loading, per-image preprocessing, process startup, queue coordination, output locking, and publication. Those are possible contributors to the remaining runtime, but this benchmark did not isolate their shares. Four workers are the best measured setting on this machine; other machines should run their own sweep before changing the setting.

## Complete output CSV

The submission candidate was produced with four workers in 4.495 seconds. `just evaluate-pipeline` scored all 100 images at 0.9952 character accuracy, with 96 exact matches and no recognition failures, above the required 0.50 threshold. An independent row check found 100 rows, 100 unique IDs, all expected filenames exactly once, and finite nonnegative per-image timings. The run reported zero successful loader and recognizer retries.

## Earlier machine report

The prior report recorded results from an Intel Core i3-10110U host with Tesseract 5.5.3.20260724: medians were 26.242 seconds at one worker, 17.145 seconds at two workers, and 14.034 seconds at four workers. That report predates per-run retry reporting and used a different Tesseract version. We keep it as historical context and do not combine it with the measurements above.

## Submission status

- The verified 100-image CSV is in the local ignored `results/issue7/final-output/` directory. Preserve it before removing this worktree.
- The source ZIP and PowerPoint need to be located or prepared and checked against the issue's submission requirements.
- Both teammates still need to review the source ZIP, CSV, and PowerPoint and confirm they can explain their contributions and the shared design.
- The submission deadline is November 5, 2026, 10:00 AM Asia/Manila. Do not submit coursework automatically.
