# Master recovery and shutdown

The master owns the pending image queue and the authoritative assignment ledger. Recovery and output publication are coordinated under the master's condition lock. Image reads and Pyro network work stay outside that lock.

## Assignment deadline and replay

- Each assignment has a 90-second deadline, separate from the worker's 20-second RPC timeout. The deadline starts when the master reserves an image for a worker process. The budget covers the recognizer's two possible 30-second attempts plus 30 seconds for transfer and local processing; integrated real-OCR acceptance should confirm that budget on the target host.
- A worker retrying a lost `get_work` response with the same request ID receives the same image bytes and attempt token while the assignment is active.
- When the deadline expires, the master removes the old process ownership and invalidates the old request ID and attempt token. The image returns to the pending queue with a fresh token for its next assignment. The expired request ID cannot allocate another image.
- The master permits at most two reassignments per image: three total assignments including the initial attempt. If all three deadlines expire, the image is terminally failed with stage `worker_recovery` and exception type `AssignmentTimeout`.
- Results carrying an expired or superseded token are rejected. A duplicate of an already accepted result remains idempotently acknowledged, without changing the output.

The deadline is the current lost-worker detection mechanism. A stopped or unreachable process is recognized as lost when its assignment expires; workers do not need shared storage, callbacks, or heartbeats.

## Output on failure

The master writes `ocr_results.csv` only when every discovered image has a successful result. If a recovery limit is exhausted, the master preserves successful rows in `ocr_results.partial.csv`, writes per-image diagnostics to `ocr_failures.csv`, preserves any previous complete CSV as `ocr_results.previous.csv`, and exits with status 1. Source-read and worker-reported failures remain visible per-image failures.

## Bounded waits and shutdown

- The master exits after 60 seconds if no worker connects.
- After a worker connects, 180 seconds without image/result progress stops the run. Repeated `wait` polling does not extend this deadline.
- Once every image is completed or terminally failed, each responding worker process receives `shutdown` on its next work request. The master allows 30 seconds, plus at most one Pyro poll interval, for known responsive processes to request shutdown. Assignment owners already declared unresponsive do not hold shutdown open.
- Ctrl+C stops new assignments and begins the same bounded shutdown window. An in-flight result may still be accepted during that window; anything unfinished is recorded as incomplete in the partial/failure outputs.

## Local verification and acceptance

Run deterministic recovery checks without the course dataset or Tesseract:

```powershell
just test tests/test_distributed.py
just verify
```

The distributed tests use real Pyro5 RPCs with a master subprocess and spawn-based worker processes. They cover replay, stale-result rejection, stopped-worker reassignment, retry exhaustion, output preservation, cancellation, bounded inactivity, and clean shutdown. The local-container stopped-worker demonstration with real OCR remains the integrated acceptance work in [issue #26](https://github.com/qu1r0ra/parallel-ocr-pipeline/issues/26); allow the 90-second assignment deadline when planning that run.
