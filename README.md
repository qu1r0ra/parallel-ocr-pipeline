# Parallel OCR Pipeline

A native Windows OCR pipeline for CSC611M Machine Project 1, now extended with a direct-Pyro5 master-to-worker workload for Machine Project 2. The MP1 application remains available alongside the distributed commands. MP2 worker nodes can run multiple spawned worker processes and can be deployed as isolated Docker Compose services. The master reassigns expired work; see [master recovery and shutdown](docs/master-recovery.md). The integrated stopped-worker acceptance run is tracked in [issue #26](https://github.com/qu1r0ra/parallel-ocr-pipeline/issues/26).

## Start on Windows

1. Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and [just](https://just.systems/man/en/packages.html) if they are not already available. With WinGet:

   ```powershell
   winget install --id=astral-sh.uv -e
   winget install --id Casey.Just --exact
   ```

   The recipes use Windows PowerShell (`powershell.exe`), which is included with Windows; PowerShell 7 is optional.

2. Install the native Tesseract executable using the [official Windows installation guidance](https://tesseract-ocr.github.io/tessdoc/Installation.html). Make `tesseract.exe` available on `PATH`.
3. Put the course-provided files in the local locations listed in [`local-assets/README.md`](local-assets/README.md).
4. From this directory, run:

   ```powershell
   just setup
   just prepare-assets
   just check-environment
   just verify
   ```

The setup task installs the uv-managed Python 3.15 interpreter and creates the project `.venv` from the committed lockfile. See [`docs/setup-windows.md`](docs/setup-windows.md) for the component distinctions and troubleshooting.

## Useful files

- [`config.txt`](config.txt) contains the pipeline settings to edit before running.
- [`docs/requirements.md`](docs/requirements.md) summarizes the Machine Project 1 handout.
- [`docs/requirements-mp2.md`](docs/requirements-mp2.md) summarizes the Machine Project 2 distributed OCR handout.
- [`docs/agents/mp2-development.md`](docs/agents/mp2-development.md) routes MP2 contributors to the accepted design and explains which MP1 guidance remains applicable.
- [`docs/pyro5-rpc-contract.md`](docs/pyro5-rpc-contract.md) defines the initial direct URI, message validation, replay, output, timing, and shutdown behavior.
- [`docs/ocr-contract.md`](docs/ocr-contract.md) defines image ownership, failures, output expectations, and timing.
- [`docs/ocr-evaluation.md`](docs/ocr-evaluation.md) records recognizer settings, preprocessing, failure types, and the recognition evaluation.
- [`docs/integrated-validation.md`](docs/integrated-validation.md) records pipeline CSV scoring and lifecycle checks for issue #6.
- [`docs/benchmark-results.md`](docs/benchmark-results.md) records ticket #7's repeated measurements, analysis, and submission status.
- [`docs/team-handoff.md`](docs/team-handoff.md) records the accepted ownership split and next tasks.

Score a completed pipeline CSV against the same labels and character metric used by standalone evaluation:

```powershell
just evaluate-pipeline path/to/ocr_results.csv
```

## Run the pipeline

Edit `config.txt` to set `image_dir` and `n_workers`. The file is ready to use with the prepared dataset and the lowest-median worker count from this host's 1–32 sweep:

```text
image_dir=local-assets/dataset/images
n_workers=11
```

Adjust the worker count for the target machine. Relative image paths are resolved from the config file's directory. From the repository root, run:

```powershell
just pipeline
```

The pipeline writes results beside the config file:

- `ocr_results.csv` contains the complete run.
- `ocr_results.partial.csv` and `ocr_failures.csv` are written when images or the run fail; a prior complete CSV is preserved.

The command prints total processing time from thread startup through output publication. Exit status `0` means success, `1` means a runtime or image failure, `2` means invalid configuration or input, and `130` means the run was cancelled with Ctrl+C.

The pipeline defaults Tesseract's native thread limit (`OMP_THREAD_LIMIT`) to `1`, so Python workers control the parallelism. An explicit environment value overrides this default.

## Run the first MP2 workload

Copy `master_config.example.txt` to `master_config.txt` on the master and `worker_config.example.txt` to `worker_config.txt` on the worker. Set `image_dir` to the master's local dataset path. Set `master_host` to the address reachable from the worker (use `127.0.0.1` only when both processes run on the same machine). The worker does not need the dataset or any shared folder. Start the processes in separate terminals:

```powershell
just master
just worker
```

The master writes `ocr_results.csv` beside its config only when every discovered image succeeds. Before processing, it moves an older complete CSV to `ocr_results.previous.csv`; success replaces it with the new output, while failure preserves the backup and writes `ocr_results.partial.csv` and `ocr_failures.csv`. `n_workers` is the number of spawned child processes on this worker node. For local container deployment and replica scaling, see [`docs/setup-containers.md`](docs/setup-containers.md). Master-side worker-failure reassignment remains in #24.

## Verify and benchmark

`just test tests/test_pipeline.py` runs deterministic pipeline tests without Tesseract. For real OCR, install Tesseract, prepare the model and images, then run `just check-environment` and `just pipeline`. `just recognize <image>` and `just evaluate` remain separate OCR tools; the evaluator measures recognition quality against the labels.

Run `just benchmark` to compare the full configured image workload with every worker count from 1 through 32. It uses `image_dir` from `config.txt`, overrides `n_workers` for the comparison, and does not modify the config. The benchmark performs one warm-up and ten measured runs per worker count, interleaving measured counts. It sets `OMP_THREAD_LIMIT=1` only for benchmark child processes. Successful run outputs are temporary and removed; if any run fails, the benchmark stops and prints the location of preserved diagnostic artifacts. See [`docs/benchmark-results.md`](docs/benchmark-results.md) for the recorded sweep and visualization.

The benchmark reports each warm-up and measured run's elapsed time and successful loader/recognizer retry counts. It also reports each worker count's ten runtimes, the retry counts per measured run, median, range, and speedup relative to the one-worker median. Speedup uses full pipeline elapsed time, not the sum of per-image CSV times. Record the machine and results when comparing performance; results are specific to the tested host.
