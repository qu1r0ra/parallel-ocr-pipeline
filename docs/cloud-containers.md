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

- **Run native processes; Docker is out.** No Docker is installed, and an unprivileged LXC cannot host it without nesting the owner cannot enable. The cloud driver starts `just master` and `just worker` directly, over SSH.
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

## State of provisioning

Provisioned identically on all three on 2026-11-24 from commit `381820a` (`main`); reprovision only if a row below no longer holds.

| Item | State |
| --- | --- |
| SSH | dedicated ed25519 key `csc611m-cloud-bench` in `/root/.ssh/authorized_keys`; the private key stays on the owner's PC |
| Packages | `apt install tesseract-ocr tesseract-ocr-eng curl`; Tesseract **5.3.4** |
| `uv` | 0.13.9 in `/root/.local/bin` (add it to `PATH` in non-interactive SSH) |
| Python | 3.15.2, fetched by `uv sync --locked --no-dev` |
| Code | `git archive` tarball extracted to `/root/ocr`; the commit SHA is in `/root/ocr/COMMIT` (no Git or GitHub token on the containers) |
| Model | `/root/ocr/local-assets/models/eng.traineddata`, SHA-256 `7d4322bd…70b2` (identical on all three) |
| Dataset | server0 only, `/root/ocr/local-assets/dataset/images` (100 images, hash-matched to the owner's copy) |
| Runs | per-run directory `/root/run/<id>/`; the master writes its CSV beside its config file |

Smoke run (server0 master, server1 worker node, 2 processes, no Docker): 100 images in about 4.4 s end to end; 97 exact matches, character accuracy 0.9964 (`evaluate-pipeline`).
