# Concurrency and shutdown design

**Status: accepted.** Both teammates confirmed this plan during joint planning on October 12, 2026, for [#3](https://github.com/qu1r0ra/parallel-ocr-pipeline/issues/3). Imman implements the pipeline in [#5](https://github.com/qu1r0ra/parallel-ocr-pipeline/issues/5); Quirora implements recognition in [#4](https://github.com/qu1r0ra/parallel-ocr-pipeline/issues/4).

## Agreed decisions

| Topic | Choice |
|---|---|
| Workers | One loader and explicitly created, non-daemon `threading.Thread` workers. `n_workers` excludes the loader. |
| Shared queue | `queue.Queue(maxsize=2 * n_workers)`, with built-in synchronization and `shutdown()`. |
| Output | Workers write successful rows directly under a `threading.Lock`, in completion order. |
| Output location | Write result files beside the config file. |
| Recovery | One additional attempt at each failing stage for known transient loading or OCR failures; terminal image failures do not stop other images. |
| Success | Publish `ocr_results.csv` only when every input succeeds; preserve the previous successful CSV until replacement succeeds. |
| Image failures | Save successful rows as `ocr_results.partial.csv`, write a separate failure report, and exit 1. |
| Empty input | Empty or image-less input is a configuration error, exit 2. |
| Python | Standard CPython 3.15.0 on both Windows machines. |

The professor confirmed that any Python standard-library concurrency or synchronization primitive is permitted; OCR and image libraries may be third-party. A custom monitor is unnecessary for course coverage. `queue.Queue` directly implements bounded producer-consumer handoff; the students still explain backpressure, output locking, ownership, recovery, and termination.

Threads keep shared state in one process and avoid serialization and Windows child-process startup coordination. Tesseract runs as a separate process. An exploratory raw `pytesseract` probe on 40 images, excluding preprocessing, took approximately 4.5 s, 2.4 s, 1.3 s, and 1.2 s at 1, 2, 4, and 8 threads. This supports the choice but does not replace full-pipeline benchmarks.

## Inputs and configuration

- Main validates `key=value` configuration. Blank lines and `#` comments are ignored; unknown or duplicate keys are rejected. `n_workers` must be an integer of at least 1. Relative `image_dir` resolves against the config file's directory.
- Main lists images non-recursively, filters supported extensions, excludes hidden and `._*` metadata files, sorts filenames, and assigns IDs 1..N before starting work. Completion order never changes identity.
- Missing input, invalid configuration, or zero candidate images exits 2 without publishing new output. Existing successful output remains intact.
- Write `ocr_results.csv` beside the config file.
- Ground-truth labels are evaluation data only; recognition and retry decisions never consult them.

## Shared state and ownership

```text
main: validate, assign IDs, start timer and threads
  |
  +-- loader -- put(id, filename, detached image) --> bounded queue.Queue
  |                                                      |
  |                                                     get()
  |                                                      v
  +-- workers -- recognize, optional retry --> output Lock --> temporary CSV
  |                                             |
  |                                      terminal failure records
  |
  +-- join threads --> publish complete or partial output --> stop timer
```

| Shared state | Protection |
|---|---|
| Queued jobs | `queue.Queue` provides its own locks and waiting protocol. |
| CSV stream, successful-row count, terminal image failure records | One output `Lock`; loader/workers record outcomes, main reads after joins. |
| First fatal pipeline error | Recorded under the output `Lock`; subsequent errors remain visible in diagnostics. |
| Global stop request | `threading.Event`, set for cancellation or fatal pipeline errors. |

Never hold the output lock while loading, recognizing, retrying, or blocking on the queue. Queue synchronization does not protect the CSV.

The loader fully loads and detaches each image before enqueueing `(id, filename, image)`. It owns the image until `put()` succeeds; the queue then owns it until a worker dequeues it. The worker retains ownership across recognition attempts and closes it in `finally`. A failed enqueue leaves cleanup with the loader. Workers close queued images without recognizing them during global stopping; main closes any leftovers after joining, including when workers have died unexpectedly. The recognizer preserves the caller's input and closes only its own derived images.

## Per-image recovery

- Loading and recognition each allow at most two attempts: the initial attempt plus one retry for a known transient failure, such as temporary file-access contention or a Tesseract timeout. The loader retries `PermissionError` once; other image decoding and file errors are terminal for that image. Loader retries stay in the loader; recognition retries stay with the worker. Never re-enqueue a job for retry.
- Clearly corrupt/unsupported images and non-transient recognition errors become terminal image failures immediately. Check the global stop event before another attempt.
- A terminal failure records fixed ID, filename, stage (`load` or `recognize`), attempts at that stage, exception type, and message. A failed load never queues an invalid image. Other inputs continue.
- A recovered image writes exactly one successful row. An unrecovered failure never writes invented OCR text. A legitimate empty OCR string is successful inference, not an exception or an automatic retry trigger.
- Missing shared OCR prerequisites, output-write errors, broken coordination, and unexpected exceptions outside per-image processing are global failures; they stop the run.

## Output and observable outcomes

Workers write successful rows to a temporary CSV with a header and correct `csv` escaping. Each row contains ID, filename, extracted text, and processing milliseconds. Main closes streams after joining every thread, then checks accounting and publishes output.

- **Success:** loader finished, all threads terminated, no terminal image failures or fatal error, and exactly N unique successful identities. Use `os.replace` from a temporary file in the destination directory to publish `ocr_results.csv`. Exit 0 only after publication succeeds.
- **Terminal image failures:** every candidate has either a successful row or a terminal failure record, without duplicates. Publish successful rows as `ocr_results.partial.csv` and failures as `ocr_failures.csv`. Return 1. Diagnostics give counts and state that any existing `ocr_results.csv` belongs to a previous successful run.
- **Global failure/cancellation:** stop further processing and join threads. Return 1 for runtime/global errors and 130 for Ctrl+C. Preserve completed rows as partial output when storage remains writable; record the global error and unprocessed inputs in `ocr_failures.csv`. Diagnostics identify the cause and completed count. Preserve previous successful output.
- Stage both partial-run artifacts before replacing either destination. If publication fails, restore the previous pair where possible and report any rollback problem. Successful publication removes obsolete partial/failure artifacts; cleanup errors are reported explicitly.

| Situation | Outcome |
|---|---|
| Every image succeeds, including recovered attempts | Exit 0; complete CSV with a header and N unique rows. |
| Invalid/missing config, invalid worker count, missing/empty/image-less input | Exit 2; diagnostics; no newly published output. |
| Terminal loading or OCR failures | Continue remaining images; partial CSV and failure report; exit 1. |
| Fatal pipeline/environment/output error | Stop and join; diagnostics; partial artifacts when writable; exit 1. |
| Ctrl+C | Stop and join; diagnostics; partial artifacts when writable; exit 130. |

The assignment's complete-output requirement applies to the submitted successful run. Partial output is a recovery artifact, not evidence that every image was recognized.

## Shutdown

After loading finishes, call graceful `queue.shutdown()`. Workers drain queued jobs and exit when `get()` raises `queue.ShutDown`; an empty queue alone does not mean production is finished.

For cancellation or a global failure, set the stop event and call graceful `shutdown()` to reject new jobs and wake a loader blocked in `put()`. Workers check the event after dequeueing and close remaining images without OCR. Avoid immediate shutdown that discards image objects before explicit cleanup. An active OCR call finishes or reaches its timeout; the worker closes its image and skips subsequent inference. Per-image failures do not shut down the queue.

Main joins all non-daemon threads in timed `join()` loops so Ctrl+C remains responsive on Windows. A caught Ctrl+C requests shutdown, then waits for active work to finish before writing partial artifacts and returning 130. Thread-entry exception handlers record global failures and request shutdown, preventing silent worker death. Main drains and closes any remaining jobs after joins. Completion is verified from joined threads and outcome accounting, rather than relying on queue emptiness or `Queue.join()`.

The recognizer has a per-attempt Tesseract timeout. This bounds Tesseract calls, not arbitrary file I/O or an injected recognizer; do not claim a universal runtime bound from that timeout.

## Timing and benchmarks

- Per-image time uses `time.perf_counter()` and includes preprocessing and all recognition attempts. It excludes loading, queue wait, and output-lock wait.
- Total time starts immediately before thread startup/loading and ends after joins, stream closing, and output publication. It includes loading, retries, coordination, and output. Configuration validation and enumeration are outside it.
- Set `OMP_THREAD_LIMIT=1` by default and record it. Keep dataset, retry policy, OCR timeout, model, preprocessing, and timer boundaries constant across worker counts.
- Compute speedup from repeated complete successful runs. Report incomplete runs separately. Real OCR quality and performance belong to OCR/benchmark work, not lightweight correctness tests.

## Verification and implementation handoff

Use `run(config_path, recognizer=None) -> int` as the complete-app seam. A deterministic substitute recognizer derives text from image contents, records overlap, and can fail once or persistently. Run hang-sensitive cases in subprocesses with timeouts and terminate on expiry; a watchdog thread cannot terminate hung non-daemon workers.

Verify complete output/unique IDs with one and several workers; filename association; CSV punctuation/newline escaping; observed overlap; invalid/empty input; successful retry without duplicate rows; exhausted failures while later images still succeed; corrupt images without retry; failure-report contents; old-output preservation; global output errors; cancellation with a full queue; thread termination; and image cleanup after failed enqueue, retry, processing, and stopping.

The project requirements, lockfile, Ruff/basedpyright targets, and setup instructions now target Python 3.15. Verify the locked installation, tooling, Pillow imports, and a real Tesseract call on both Windows machines. Python 3.15.0 is the [stable release](https://www.python.org/downloads/release/python-3150/). [Pillow 12.3.0](https://pypi.org/project/pillow/) publishes a standard Windows x64 `cp315` wheel; [pytesseract 0.3.13](https://pypi.org/project/pytesseract/) publishes a universal Python wheel. Availability supports the target but does not replace runtime checks.

The [OCR contract](ocr-contract.md) remains the independent implementation seam. This accepted design supplies the owner-controlled decisions for #5; interpreter migration and substantive OCR/pipeline code are follow-on work.
