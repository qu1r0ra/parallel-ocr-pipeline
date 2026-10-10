# Concurrency and shutdown design (draft)

**Status: draft, pending Imman's endorsement.** Issue [#3](https://github.com/qu1r0ra/parallel-ocr-pipeline/issues/3) is not satisfied until both teammates endorse this document. Items marked **Pending** are Quirora's recommendations awaiting Imman's agreement; items marked **Decided** are technical defaults that stand unless Imman objects. Imman owns the implementation ([#5](https://github.com/qu1r0ra/parallel-ocr-pipeline/issues/5)).

## Decisions

| # | Topic | Choice | Status |
|---|---|---|---|
| 1 | Worker backend | `threading` threads. | Pending |
| 2 | Shared queue | Hand-written bounded-buffer monitor: one `threading.Lock`, `not_full` and `not_empty` `Condition`s, `while` predicate rechecks, plus `close()` and `abort()`. | Pending |
| 3 | Result writing | Workers write rows directly to the CSV under a `Lock`, in completion order. | Pending |
| 4 | Per-image failure | Fail fast. Rows go to `ocr_results.csv.tmp`, renamed to `ocr_results.csv` only on full success. | Pending |
| 5 | Empty or image-less `image_dir` | Configuration error, exit 2, no CSV. | Pending |
| 6 | Python version | Not pinned to 3.11; move to the latest stable Python once both machines can install it. | Pending |

### Rationale

- **Threads.** Threads are what the course has covered and the simplest to explain: the queue and results are ordinary shared state. The recognizer calls `pytesseract`, which runs `tesseract.exe` as a separate process, so the GIL does not serialize OCR. Probe on the dev machine (12 logical cores, 40 dataset images, raw `pytesseract` in a thread pool, no preprocessing): 1 thread 4.5 s, 2 threads 2.4 s, 4 threads 1.3 s, 8 threads 1.2 s. Processes would add picklable jobs, a `__main__` guard (Windows starts children by re-importing the program), and a cross-process CSV lock. Revisit only if benchmarks show preprocessing serializing on the GIL.
- **Monitor.** Synchronization is 50% of the grade and the handout lists a student-designed monitor as acceptable. It follows the Oct 5 bounded-buffer protocol: `append` waits on `not_full`, `remove` waits on `not_empty`, both in `while` loops. Production Python would normally use `queue.Queue`, which is the same structure internally; on Python 3.13+ it also has `shutdown()`. Fallback if Imman prefers it: `queue.Queue` for jobs, an explicit `Lock` for CSV and counters, and an `Event` or `shutdown()` for abort.
- **Fail fast.** One header plus exactly one row per input; a partial run can never produce a final-looking CSV. The alternative (continue and report) leaves a plausible incomplete file.
- **Empty directory.** An image-less `image_dir` is almost always a wrong path; a header-only success would hide it.

## Decided defaults

- **Identity.** The main thread lists image files non-recursively, filters by image extension, skips hidden and `._*` files, sorts by name, and assigns IDs 1..N before work starts. The loader enqueues `(id, name, image)`.
- **Queue capacity.** `2 × n_workers`; the loader blocks when full.
- **Image ownership.** The loader reads and detaches each image before enqueueing. The dequeuing worker owns it and closes it after recognition, including on failure (see [`ocr-contract.md`](ocr-contract.md)).
- **Worker count.** `n_workers` excludes the loader: one loader thread plus `n_workers` worker threads.
- **Timers.** Per-image time is `time.perf_counter()` around `recognize()` only, excluding queue wait. Total time starts immediately before the loader starts and stops after all threads are joined and the CSV is closed and renamed. Config parsing and validation are outside the timer.
- **Config.** `key=value` lines; blank lines and `#` comments ignored; unknown or duplicate keys rejected; `n_workers` an integer of 1 or more; a relative `image_dir` resolves against the config file's directory.
- **Tesseract native threads.** The pipeline sets `OMP_THREAD_LIMIT=1` by default; the benchmark records the setting. The probe showed no difference on these small images.
- **Hung Tesseract.** The recognizer passes a per-image `timeout` to `pytesseract`, so a hang becomes a recognition error (owned by [#4](https://github.com/qu1r0ra/parallel-ocr-pipeline/issues/4)).
- **Exit codes.** 0 success, 2 configuration or usage error, 1 runtime failure, 130 cancelled.
- **Success rule.** Exit 0 only if no error was recorded, the loader finished, and rows written equals the number of images.

## Shared state and ownership

```text
main thread ── validates config, lists/sorts images, assigns IDs, starts timer
   │
   ├─ loader thread ──append(job)──▶ BoundedBuffer (Lock + not_full/not_empty)
   │                                       │ remove()
   │                                       ▼
   └─ worker threads (n) ── recognize(image) ──▶ CSV sink (Lock): write row, count++
                                                  └─▶ ocr_results.csv.tmp
```

| Shared state | Guarded by | Writers | Readers |
|---|---|---|---|
| Buffer slots, `count`, `in`/`out`, closed/aborted flags | buffer `Lock` + conditions | loader, workers | loader, workers |
| CSV file handle, rows-written count | sink `Lock` | workers | main (after join) |
| First recorded error | sink `Lock` (or a dedicated one) | loader, workers | main |

Each job's image is owned by exactly one thread at a time: the loader until `append` returns, then the worker that removed it.

## Shutdown protocol

- **Normal.** After enqueueing the last job the loader calls `close()`. `remove()` returns "no more work" only when the buffer is closed and empty, so workers drain all queued jobs and exit. Main joins the loader and all workers, closes and renames the CSV, and stops the timer.
- **Failure.** A loader or worker that hits an exception records it (the first error wins; later ones are logged), then calls `abort()`: set the aborted flag, discard queued jobs, `notify_all` on both conditions. The loader blocked on `not_full` and workers blocked on `not_empty` wake, see the flag, and exit. Workers finish at most the image they are already recognizing, bounded by the recognizer timeout.
- **Cancellation.** Main joins with `join(timeout=...)` in a loop so Ctrl+C is delivered on Windows, then calls `abort()` and joins the rest. Exit 130.
- **Unexpected exceptions.** Every thread body catches `Exception` and records it as a failure, so no thread dies silently.
- **After a failed or cancelled run.** Close and delete the `.tmp` file; no final CSV exists.
- **Stale output.** Once configuration validates and before loading starts, any existing `ocr_results.csv` is deleted.

## Outcomes

| Situation | Observable outcome |
|---|---|
| Normal completion | Exit 0; `ocr_results.csv` with a header and N rows, IDs 1..N, each once. |
| Missing or malformed config, unknown or duplicate key | Exit 2, message on stderr, no CSV written. |
| Invalid `n_workers` (non-integer, below 1) | Exit 2, message on stderr, no CSV written. |
| Missing `image_dir` | Exit 2, message on stderr, no CSV written. |
| Empty or image-less `image_dir` | Exit 2, message on stderr, no CSV written. |
| Unreadable image | Loader aborts; exit 1; stderr names the file; no final CSV. |
| Recognition error or timeout | Worker aborts; exit 1; stderr names the file; no final CSV. |
| Cancellation (Ctrl+C) | Abort and join; exit 130; no final CSV. |

All outcomes terminate within a bound: the recognizer timeout plus join overhead.

## Verification plan

- **Seam.** The application is `run(config_path, recognizer=None) -> int`; `None` selects the real recognizer and the CLI wraps `run`. Tests inject a deterministic fake recognizer through the image-to-text interface.
- **Fake recognizer.** Derives its text from image content so text-to-file association is checkable, sleeps briefly, and records the maximum number of concurrent calls to demonstrate overlap with several workers.
- **Hang bound.** Each test runs `run()` under a watchdog thread with a timeout, so a hang fails instead of blocking the suite.
- **Cases.** Complete output and unique IDs with 1 and several workers; deterministic ID-to-filename mapping; CSV escaping of punctuation and newlines; overlap observed with `n_workers >= 2`; each outcome row above via subprocess tests for exit codes 2 and in-process tests for failures and cancellation; no `ocr_results.csv` after a failed run.
- **Excluded.** Real OCR accuracy and speed thresholds stay out of ordinary tests; they belong to [#4](https://github.com/qu1r0ra/parallel-ocr-pipeline/issues/4) and the benchmark.

## Open items

- Imman's decision on each **Pending** row and on the defaults.
- Python version both machines can install, then update `requires-python`, tool targets, and `uv.lock` in a separate change.
- Imman's schedule for review and for starting #5 (integration milestone: October 22).
