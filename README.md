# Parallel OCR Pipeline

A native Windows development scaffold for CSC611M Machine Project 1. It defines the project environment, local asset workflow, quality checks, and the interface between OCR and pipeline work. It does not yet implement OCR or a runnable pipeline.

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

The setup task installs the uv-managed Python 3.11 interpreter and creates the project `.venv` from the committed lockfile. See [`docs/setup-windows.md`](docs/setup-windows.md) for the component distinctions and troubleshooting.

## Useful files

- [`config.example.txt`](config.example.txt) shows the agreed future pipeline configuration.
- [`docs/requirements.md`](docs/requirements.md) summarizes the course handout for project contributors.
- [`docs/ocr-contract.md`](docs/ocr-contract.md) defines image ownership, failures, output expectations, and timing.
- [`docs/team-handoff.md`](docs/team-handoff.md) records the accepted ownership split and next tasks.

`just` lists the available tasks. There is no `ocr`, `pipeline`, or benchmark command until those implementations exist. `just run <script.py>` only runs the named Python script; it does not imply that a complete OCR application is present.
