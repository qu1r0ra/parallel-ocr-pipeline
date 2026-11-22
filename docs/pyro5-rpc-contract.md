# MP2 direct Pyro5 RPC and lifecycle contract

This document records the shared RPC boundary established in issue #23. The accepted design is in [MP2 spec #22](https://github.com/qu1r0ra/parallel-ocr-pipeline/issues/22); check the live tickets for implementation status.

## Topology and startup

- The master starts one Pyro5 `Daemon` bound to `0.0.0.0:<port>` and registers object ID `ocr.master`.
- A worker constructs the direct URI `PYRO:ocr.master@<master_host>:<master_port>`. There is no name server, worker-side daemon, callback, shared memory, or shared volume.
- The master reads and enumerates image files. It sends one encoded image byte payload per `get_work` request; workers receive no source path or labels.
- A worker node starts the configured `n_workers` child processes. Each process owns its proxy and requests one image at a time.
- RPC calls have a 20-second timeout. The worker makes up to two explicit attempts (one retry) with the same request ID or result attempt token, with Pyro's automatic retries disabled. Each process may hold one active image assignment at a time; the master caps active process identities at 32.
- Until its first master response, a worker process retries `get_work` up to 6 attempts with 1, 2, 4, 8, and 16 s waits, reusing one request ID, so a master or DNS entry that is still starting does not fail the node (#38). The total wait is bounded at 45 s from the first attempt: no retry starts once the next wait would reach that deadline, and an attempt already in flight can still run its 20 s timeouts past it. Whichever limit hits first exits the process with status 1. A stop signal during a wait ends the retries at once, and the worker exits with status 0 through its normal stop path. After the first response, a communication failure exits immediately as before.

## Identity and messages

Each worker process creates a process-incarnation ID from its OS process ID and a random UUID. Each pull has a new UUID request ID. Each image assignment has a master-generated UUID attempt token. The master binds the token to the node ID, process incarnation, and request ID that received it.

`get_work(node_id, process_id, request_id)` returns one of:

- `work`: `image_id`, `filename`, `image_bytes`, `request_id`, and `attempt_token`.
- `wait`: no unassigned images remain while another assignment is still active; the worker pauses briefly and makes a new request.
- `skip`: the master could not read or transfer that particular file; the failure is recorded and the worker asks for another image.
- `shutdown`: no queued or active assignments remain.
- `rejected`: identity or request input is invalid; the request does not consume work.

The master accepts `submit_result(node_id, process_id, request_id, attempt_token, outcome)` only for the matching active assignment. Success outcomes contain `text` and worker-side `processing_time_ms`; failure outcomes contain a stage, exception type, and diagnostic message. Invalid or stale tokens are rejected without changing image state. An exact duplicate result submission is acknowledged idempotently. A different result under the same identity is rejected.

## Bounds and replay

- Each transferred image is limited to 16 MiB. The size is checked before and after reading to guard against file changes. Pyro's message cap is about 32.25 MiB to allow for Serpent's base64 encoding overhead plus message metadata.
- Identifiers, text, diagnostic strings, result shapes, processing time, and status values are validated at the public RPC boundary. Result text is limited to 1,000,000 characters; failure diagnostics are limited to 2,000 characters. The master accepts at most 32 active worker-process identities, with one image assignment active per process.
- A request ID is unique within a process incarnation. Before a result is accepted, replaying its pull request returns the same assignment, token, and bytes. After result acceptance, that pull request replays as `completed` and its image bytes are discarded. A process incarnation is unique per worker launch. An assignment token authorizes one result for one exact assignment.
- The worker sends one image per request. Failed submissions can be retried with the same request ID and token. The master expires assignments after 90 seconds, permits at most two reassignments per image, rejects superseded requests/results, and records an `AssignmentTimeout` failure after exhaustion. See [master recovery and shutdown](master-recovery.md).

## Timing, output, and termination

`processing_time_ms` measures only the call to the existing recognizer after image bytes have arrived and the image has been decoded. Network transfer, image decode, and queue wait are excluded. Values are elapsed wall-clock milliseconds measured by `perf_counter_ns()` on the worker.

The master orders input files deterministically and assigns sequential integer IDs beginning at 1. It writes `ocr_results.csv` with fields `image_id,filename,text,processing_time_ms` only when every input image has a successful result. CSV escaping is handled by Python's CSV writer. Before processing starts, an existing complete CSV is moved to `ocr_results.previous.csv`. A successful run replaces it with the new complete CSV and removes the backup. A failed or interrupted run preserves the backup and writes successful rows to `ocr_results.partial.csv` plus failures/incomplete work to `ocr_failures.csv`; it leaves no current-run `ocr_results.csv`.

After every image has a terminal outcome, workers receive `shutdown` on their next pull; the daemon waits up to 30 seconds for known responsive workers before exiting. A master with no connecting worker stops after 60 seconds. A connected worker that makes no image/result progress for 180 seconds stops the run; repeated `wait` polling does not reset that deadline. Ctrl+C stops new assignments and starts the bounded shutdown window. See [master recovery and shutdown](master-recovery.md) for recovery outputs and operator behavior.

## Local development

Use `master_config.example.txt` and `worker_config.example.txt` as templates, then run `just master` and `just worker` in separate terminals. The real network test uses a master subprocess and a spawn-created worker process with a deterministic recognizer, so it needs no Tesseract binary or course dataset.
