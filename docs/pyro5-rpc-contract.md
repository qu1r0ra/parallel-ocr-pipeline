# MP2 direct Pyro5 RPC and lifecycle contract

This document defines the first implementation slice from issue #23. The parent design remains [MP2 spec #22](https://github.com/qu1r0ra/parallel-ocr-pipeline/issues/22); this contract records the boundary both partners can review before dependent work begins.

## Topology and startup

- The master starts one Pyro5 `Daemon` bound to `0.0.0.0:<port>` and registers object ID `ocr.master`.
- A worker constructs the direct URI `PYRO:ocr.master@<master_host>:<master_port>`. There is no name server, worker-side daemon, callback, shared memory, or shared volume.
- The master reads and enumerates image files. It sends one encoded image byte payload per `get_work` request; workers receive no source path or labels.
- For this first slice, `n_workers` must be `1`. The config value is validated but process fan-out belongs to issue #25.
- RPC calls have a 20-second timeout. The worker makes up to three explicit attempts with the same request ID, with Pyro's automatic retries disabled. Each process may hold one active image assignment at a time; the master caps active process identities at 256.

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
- The worker sends one image per request. Failed submissions can be retried with the same request ID and token. Lost-worker detection and reassignment are defined by issue #24.

## Timing, output, and termination

`processing_time_ms` measures only the call to the existing recognizer after image bytes have arrived and the image has been decoded. Network transfer, image decode, and queue wait are excluded. Values are elapsed wall-clock milliseconds measured by `perf_counter_ns()` on the worker.

The master orders input files deterministically and assigns sequential integer IDs beginning at 1. It writes `ocr_results.csv` with fields `image_id,filename,text,processing_time_ms` only when every input image has a successful result. CSV escaping is handled by Python's CSV writer. A failed or interrupted run writes successful rows to `ocr_results.partial.csv` and failures/incomplete work to `ocr_failures.csv`; it removes any prior complete output so the current run cannot appear successful by accident.

After all results arrive, the worker makes another pull and receives `shutdown`; the daemon exits its request loop and the worker exits normally. A master with no connecting worker stops after 60 seconds. A connected worker that makes no image/result progress for 180 seconds stops the master; repeated `wait` polling does not reset that deadline. Those deadlines bound the first slice; reassignment and stronger multi-node lifecycle coordination are follow-on work.

## Local development

Use `master_config.example.txt` and `worker_config.example.txt` as templates, then run `just master` and `just worker` in separate terminals. The real network test uses a master subprocess and a spawn-created worker process with a deterministic recognizer, so it needs no Tesseract binary or course dataset.
