# Cloud containers

The cloud dataset ([benchmark evidence](agents/mp2-development.md#benchmark-evidence)) runs on three DLSU CCS cloud machines, hosted on Proxmox at `ccscloud2.dlsu.edu.ph`. They are **unprivileged LXC containers**, not VMs. Name them "LXC containers" in reports and the deck; the handout accepts separate machines, VMs, or containers.

Read this before touching them. Account names, passwords, and public SSH endpoints live only in the owner's `csc611m_accounts_grp1.xlsx` (Downloads). Keep them out of Git, logs, and summaries.

## Topology

| Role (planned) | Name | CT ID | Private IP |
| --- | --- | ---: | --- |
| master | `csc611m-01-server0` | 62097 | `10.20.201.36` |
| worker 1 | `csc611m-01-server1` | 67097 | `10.20.201.37` |
| worker 2 | `csc611m-01-server2` | 67597 | `10.20.201.38` |

- Each has 2 vCPU, 4 GiB RAM, and about 49 GiB disk, on Ubuntu 24.04 (kernel 6.17 `pve`) with system Python 3.12.3. Read from all three over SSH on 2026-11-24 (`nproc`, `free`, `df`).
- Server0 runs on Proxmox node `hera`, server1 on `artemis`, server2 on `athena`; the three containers sit on three different hosts.
- The nodes reach each other on the private `/16` (ping verified from server2 to both peers).
- Three containers cap the cluster at **two worker nodes**; that is why the cloud node sweep is one matched pair.

## Constraints that shape the design

- **Run native processes; Docker is out.** No Docker is installed, and an unprivileged LXC cannot host it without nesting the owner cannot enable. The cloud driver ([`scripts/benchmark_cloud.py`](../scripts/benchmark_cloud.py)) starts `just master` and `just worker` directly, over SSH.
- **Root is available.** Every account is root. `apt` works (verified on server2: package lists fetched; `tesseract-ocr` 5.3.4, `git`, `curl` are candidates). GitHub and PyPI are reachable. Python `urllib` gets 403 from `astral.sh`, but `curl -fsSL https://astral.sh/uv/install.sh | sh` works.
- **The Ubuntu Tesseract version differs from the Docker image's and the laptop's.** Record it in every cloud summary; it can move OCR output.
- **Expiry: the containers are tagged `exp-20261220`.** Copy cloud results and the demo recording off them well before 2026-12-20.
- **They may be stopped between sessions.** The owner's earlier session found two stopped; check status in Proxmox and start them first.

## Reach a container

Two routes exist; use SSH once a key is installed, otherwise the console.

1. **SSH** (scripted runner): public forwarded ports from the workbook, user `root`. Root *password* login is refused over SSH (the server offers `publickey,password` but rejects the root password), so only a public key works. Key installation is part of provisioning; remove it afterwards by deleting its line from `/root/.ssh/authorized_keys`.
2. **Proxmox console** (bootstrap and recovery): log in as `CSC611M-01` and choose the realm **Proxmox VE authentication server** (the default "Linux PAM" realm fails with 401). Open the container and click the top **Console** button; a bare console URL fails with `401: No ticket`. The login there is the container's root account.

Browser automation gotchas: the site has a self-signed certificate (start `playwright-cli` with `ignoreHTTPSErrors`); after opening a page, element refs may carry an `f2` frame prefix, so take them from a fresh snapshot.

Completion: `hostname` over the chosen route returns the intended `csc611m-01-serverN` name.

## Run the cloud benchmark

`just benchmark-cloud <subcommand>` runs from the owner's PC. Give it the three endpoints, master first, as `--nodes host:port,host:port,host:port` or the `CLOUD_NODES` environment variable (workbook values; keep them out of Git), and the key with `--key` (default `~/.ssh/csc611m_cloud`).

| Subcommand | Does |
| --- | --- |
| `deploy` | ships `git archive HEAD` to every node and syncs dependencies; the dataset and model stay where they are |
| `check` | prints each node's commit, model hash, Tesseract, Python, vCPUs, and memory; exits non-zero when nodes differ, and `sweep` refuses to start in that state |
| `sweep` | the 1 to 8 process sweep at 1 and 2 worker nodes, 5 interleaved reps; narrow it with `--node-counts`, `--proc-counts`, `--reps` |
| `fault` | one run that hard-kills server2's worker mid-run and reports whether the master requeued its image |

Redeploy after every code change, then `check`; the commit in `/root/ocr/COMMIT` must equal the commit you report. Plot with `just plot-benchmark <summary.json> --out <dir>`. Results and method: [cloud benchmark](benchmark-results.md#mp2-cloud-benchmark-ticket-44); raw data: [`benchmark-cloud/`](benchmark-cloud/).

Completion: `check` exits 0, and a finished sweep's summary has `invalid_samples` = 0.

## Gotchas

- **Fault timing.** An SSH round trip takes about a second and a run takes 2 to 4 s, so a kill sent over SSH lands after the run. The fault node arms a node-local `sleep; pkill -9` timer when it starts (`FAULT_KILL_DELAY_S`).
- **Kill pattern.** `multiprocessing` spawn children omit `run_worker.py` from their command line, so the kill matches `multiprocessing.spawn` and `resource_tracker` too; a kill on `run_worker.py` alone leaves orphans that keep working.
- **Recovery takes about 100 s**, because the master waits out the 90 s assignment deadline before it requeues. The recording needs that long.
- **Timing source.** The window runs from the master's first `ASSIGN` to its `Completed` line, both stamped with `$EPOCHREALTIME` on the master, so SSH latency stays out of it.
- **Windows client.** Send scripts to `bash -s` as bytes: text-mode stdin turns LF into CRLF and bash then sees a trailing CR. Git Bash `tar` needs `--force-local`, extraction on Linux needs `--no-same-owner`, and Git Bash `sha256sum` prefixes `*` to filenames.
- **Non-interactive SSH has no `uv`.** Put `/root/.local/bin` on `PATH` in every remote script.
- **`ruff format` hook.** It can reformat and fail a commit; rerun `just verify`, then commit again.

## State of provisioning

Provisioned identically on all three on 2026-11-24; `deploy` refreshes the code, and the other rows hold until a node is rebuilt.

| Item | State |
| --- | --- |
| SSH | dedicated ed25519 key `csc611m-cloud-bench` in `/root/.ssh/authorized_keys`; the private key stays on the owner's PC |
| Packages | `apt install tesseract-ocr tesseract-ocr-eng curl`; Tesseract **5.3.4** |
| `uv` | 0.13.9 in `/root/.local/bin` |
| Python | 3.15.2, fetched by `uv sync --locked --no-dev` |
| Code | `git archive` tarball extracted to `/root/ocr`; the commit SHA is in `/root/ocr/COMMIT` (no Git or GitHub token on the containers) |
| Model | `/root/ocr/local-assets/models/eng.traineddata`, SHA-256 `7d4322bd…70b2` (identical on all three) |
| Dataset | server0 only, `/root/ocr/local-assets/dataset/images` (100 images, `dataset_sha256` `48fd17e5…0c70541`, hash-matched to the owner's copy) |
| Runs | per-run directory `/root/run/<id>/`; the master writes its CSV beside its config file |

## Cloud work status

Done: the sweep, the fault runs, the recorded demo, and the copy of `/root/run` off the containers. Nothing remains except the 2026-12-20 expiry.

- **Demo recipe** (reuse only if the recording must be redone): `just benchmark-cloud` has no 1500-image mode, so a recording-length run needs a larger image set on server0 (about 1500 images runs about 60 s on 2 nodes × 1 process). Hard-stop one worker container from the Proxmox UI (Stop, not Shutdown) 10–20 s into the run; the master logs `EXPIRE … outcome=requeued` about 90 s later. A browser video captures only browser pages, so show the master log in the CT's in-page Console. Restart the container afterwards.
- **Fallbacks:** `just benchmark-cloud fault` rehearses the same failure; the IdeaPad `just acceptance` run is the live backup.
