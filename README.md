# Parallel OCR Pipeline

A native Windows OCR pipeline for CSC611M Machine Project 1. It includes a configured, multi-worker pipeline, a standalone Tesseract recognizer, and OCR evaluation tools.

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
- [`docs/requirements.md`](docs/requirements.md) summarizes the course handout for project contributors.
- [`docs/ocr-contract.md`](docs/ocr-contract.md) defines image ownership, failures, output expectations, and timing.
- [`docs/ocr-evaluation.md`](docs/ocr-evaluation.md) records recognizer settings, preprocessing, failure types, and the recognition evaluation.
- [`docs/integrated-validation.md`](docs/integrated-validation.md) records pipeline CSV scoring and lifecycle checks for issue #6.
- [`docs/benchmark-results.md`](docs/benchmark-results.md) records M6 acceptance evidence and the machine-specific performance comparison.
- [`docs/team-handoff.md`](docs/team-handoff.md) records the accepted ownership split and next tasks.

Score a completed pipeline CSV against the same labels and character metric used by standalone evaluation:

```powershell
just evaluate-pipeline path/to/ocr_results.csv
```

## Run the pipeline

Edit `config.txt` to set `image_dir` and `n_workers`. The file is ready to use with the prepared dataset and two workers:

```text
image_dir=local-assets/dataset/images
n_workers=2
```

You only need to change these settings in `config.txt`; relative image paths are resolved from the config file's directory. From the repository root, run:

```powershell
just pipeline
```

The pipeline writes results beside the config file:

- `ocr_results.csv` contains the complete run.
- `ocr_results.partial.csv` and `ocr_failures.csv` are written when images or the run fail; a prior complete CSV is preserved.

The command prints total processing time from thread startup through output publication. Exit status `0` means success, `1` means a runtime or image failure, `2` means invalid configuration or input, and `130` means the run was cancelled with Ctrl+C.

The pipeline defaults Tesseract's native thread limit (`OMP_THREAD_LIMIT`) to `1`, so Python workers control the parallelism. An explicit environment value overrides this default.

## Verify and benchmark

`just test tests/test_pipeline.py` runs deterministic pipeline tests without Tesseract. For real OCR, install Tesseract, prepare the model and images, then run `just check-environment` and `just pipeline`. `just recognize <image>` and `just evaluate` remain separate OCR tools; the evaluator measures recognition quality against the labels.

Run `just benchmark` to compare the full configured image workload with 1, 2, and 4 workers. It uses `image_dir` from `config.txt`, overrides `n_workers` for the comparison, and does not modify the config. The benchmark performs one warm-up and ten measured runs per worker count, interleaving measured counts. It sets `OMP_THREAD_LIMIT=1` only for benchmark child processes. Successful run outputs are temporary and removed; if any run fails, the benchmark stops and prints the location of preserved diagnostic artifacts.

The benchmark reports each worker count's ten total runtimes, median, range, and speedup relative to the one-worker median. Speedup uses full pipeline elapsed time, not the sum of per-image CSV times. Record the machine and results when comparing performance; results are specific to the tested host.
