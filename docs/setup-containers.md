# Local container setup

This guide runs the MP2 master and worker nodes as separate Docker containers. The master alone mounts the source dataset. Worker replicas have private container filesystems and receive image bytes through Pyro5; no dataset or output directory is mounted on a worker.

## Prerequisites and private inputs

- Docker Engine or Docker Desktop with Linux containers and Docker Compose v2.
- A prepared image dataset under `local-assets/dataset/images`; run `just prepare-assets` after placing the supplied archive as described in the Windows setup guide.
- Enough memory and CPU for the selected worker replica and process counts. Replicas on one host share its physical resources.

Copy `.env.example` to `.env` and adjust `HOST_DATASET_DIR`, `N_WORKERS`, and `MASTER_PUBLISH_PORT` as needed. Keep `.env` and course inputs private; they are not committed. The example points to this repository's prepared image directory. On PowerShell, use `Copy-Item .env.example .env`.

`HOST_DATASET_DIR` is mounted read-only into the master as `/data/images`. Each worker receives no host mounts. The container image installs Tesseract and its English model; workers do not need the supplied dataset or labels. Results stay in the stopped master container until copied out.

## Start and collect a run

Start one master and two worker nodes:

```sh
docker compose up --build --scale worker=2
```

Set `N_WORKERS` in `.env` to the number of child processes each worker node should start (from 1 to 32). Set the replica count with `--scale worker=N`. For example, two worker nodes with three child processes each use `N_WORKERS=3` and `--scale worker=2`. The master currently accepts at most 32 active process identities across the cluster, so keep the product of replicas and processes per node at or below 32.

Follow the master and worker logs in the terminal. After the containers exit, copy the result from the master container before removing the Compose project:

```sh
mkdir -p results
docker compose cp master:/tmp/ocr_results.csv ./results/ocr_results.csv
```

For PowerShell, create the destination directory and copy the output with:

```powershell
New-Item -ItemType Directory -Force results
docker compose cp master:/tmp/ocr_results.csv results/ocr_results.csv
```

Copy `ocr_results.partial.csv` and `ocr_failures.csv` the same way when the run is incomplete. Then remove containers with `docker compose down`. Worker parents forward termination to their children and wait for bounded cleanup.

Do not treat this setup as the stopped-worker recovery demonstration yet: master-side reassignment and terminal recovery are owned by #24. A worker process or node stopping may currently leave the master incomplete.

## Deploy on separate school-cloud machines later

Build or transfer the same `parallel-ocr-pipeline:local` image to each VM. Start the master with its own read-only dataset mount and publish TCP port 5000. Start worker containers with `MASTER_HOST` set to the master's reachable private IP or DNS name and `MASTER_PORT=5000`; set `N_WORKERS` independently on each worker VM. Permit worker-to-master traffic on that port. Only the master VM/container receives the image dataset, and results are copied from the master container after completion. This uses the same Pyro application protocol without shared folders or volumes. Cloud-specific firewall and VM provisioning details depend on the school's platform and will be filled in after access is provided.

## Run source checks on Linux

On a Linux development host, install the pinned Python environment with `uv sync --locked --all-groups`, then run `just verify`. The container runtime image contains application dependencies only and does not include the source-check tools. The native Windows MP1 setup remains documented in [`setup-windows.md`](setup-windows.md).
