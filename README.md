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
- [`docs/team-handoff.md`](docs/team-handoff.md) records the accepted ownership split and next tasks.

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

Exit status `0` means success, `1` means a runtime or image failure, `2` means invalid configuration or input, and `130` means the run was cancelled with Ctrl+C.

`just test tests/test_pipeline.py` runs deterministic pipeline tests without Tesseract. For real OCR, install Tesseract, prepare the model and images, then run `just check-environment` and `just pipeline`. `just recognize <image>` and `just evaluate` remain separate OCR tools. For comparable performance runs, set `OMP_THREAD_LIMIT=1` in PowerShell (`$env:OMP_THREAD_LIMIT = "1"`) before running the pipeline, and keep it the same for each worker-count comparison.
