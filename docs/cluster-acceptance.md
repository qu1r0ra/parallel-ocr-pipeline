# Cluster acceptance (#26)

`just acceptance` runs the integrated demonstration on the container host (Ubuntu laptop; see [MP2 development](agents/mp2-development.md#container-host)). It needs `.env`, the prepared dataset, and the supplied model, all private to that host.

## Procedure

`scripts/run_acceptance.py` performs each step and checks its outcome:

1. Build the image, create one master and two worker containers (`N_WORKERS=2` processes each), and copy the model into each worker.
2. Follow the master log. At the first `ASSIGN` line naming worker node 1, pause then kill that container, so its image is in flight and its result is lost.
3. Wait for the 90-second assignment deadline. The master logs `EXPIRE`, requeues the image, and logs a second `ASSIGN` to the surviving node.
4. Wait for every container to exit, copy `ocr_results.csv` from the master, and score it with `just evaluate-pipeline`.
5. Write `evidence.json`, `master.log`, and `evaluation.txt` under `results/acceptance/attempt-N/`, then remove the cluster.

If the kill misses an in-flight assignment, the check "master logged the expired assignment" fails and the script retries (default 3 attempts).

Passing means: a worker killed in flight, an `EXPIRE` for its image, reassignment to another node, master and surviving workers exit 0, exactly one row per image, and `evaluate-pipeline` passes.

## Identity

- Node: the container hostname. Process: `<pid>:<uuid>`, unique per worker child process. Capacity: `N_WORKERS` processes per node, at most 32 across the cluster.
- Each process requests one image per `get_work` Pyro5 call. The master logs `ASSIGN` with node, process, and attempt.

## Recorded run

| Item | Value |
|---|---|
| Host | `qu1r0ra-ideapad-ubuntu`: Ubuntu, Linux 7.0.0-43, i7-1165G7 (8 threads), 14 GiB |
| Software | Docker 29.10.0, Compose 5.8.0, Tesseract 5.5.0 (supplied model) |
| Commit | `708ac3a` |
| Topology | 1 master, 2 worker containers, 2 processes each |
| Failure injection | Container `addd2d72cbf6` paused and killed 6.2 s after start while processing `img0001.png` (attempt 1) |
| Recovery | `EXPIRE` for `img0001.png`, then `ASSIGN` attempt 2 to node `32c53fa4f2e3`; 101 assignments for 100 images |
| Timing | Kill to master exit 91.1 s; total 97.4 s (the 90 s assignment deadline fits real OCR) |
| Exit codes | Master 0, surviving worker 0, killed worker 137 |
| Output | 100 rows, one per image |
| Recognition | 97 exact matches, character accuracy 0.9964 (threshold 0.5) |
| Teardown | `docker compose down -v --remove-orphans`; no containers left |

The CSV and course inputs stay on the laptop. Re-run `just acceptance` after master or worker changes and replace this table with the new run.
