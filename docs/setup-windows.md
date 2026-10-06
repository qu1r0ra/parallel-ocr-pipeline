# Windows setup

The project targets native Windows with Python 3.11. `uv` manages a project-local `.venv` and installs the exact dependency set from `uv.lock`; it can install the required Python version without a separate system Python installation. Install `just` to discover and run the repository tasks. The recipes use the Windows PowerShell shell included with Windows; PowerShell 7 is optional.

## Three separate OCR prerequisites

1. **Python packages:** `Pillow` handles images and `pytesseract` calls the OCR executable. Both are application dependencies and are installed by `just setup`.
2. **Tesseract executable:** install the Windows Tesseract 5 program using the [Tesseract installation guide](https://tesseract-ocr.github.io/tessdoc/Installation.html), then put its installation directory on `PATH`. This program is not installed by uv or pip.
3. **English model:** copy the supplied `eng.traineddata` to `local-assets/models/eng.traineddata`. This file is not included in the Python environment or downloaded by the setup task.

The Tesseract check and later OCR calls should pass `--tessdata-dir` with the absolute `local-assets/models` path. This selects the supplied model directly and avoids relying on whichever English model may be bundled with a Tesseract installer. If `tesseract.exe` is not on `PATH`, set its full path for the current PowerShell session before running the environment check:

```powershell
$env:TESSERACT_CMD = 'C:\Program Files\Tesseract-OCR\tesseract.exe'
```

## Install and prepare

From the repository root:

```powershell
just setup
just prepare-assets
just check-environment
```

`just setup` installs Python 3.11 through uv, synchronizes locked application and development dependencies, and installs the fast pre-commit hooks. `just prepare-assets` reads `local-assets/supplied/dataset.zip`; it never extracts AppleDouble metadata or the labels file into the image directory. `just check-environment` verifies Python, Python packages, Tesseract, the supplied model, and the local dataset, and prints a next step for anything missing.

## Quality tasks

Run `just` or `just --list` to see task names. `just format` and `just fix` may change Python files. `just check [path]` runs Ruff linting on a selected path. `just verify` checks lock freshness, lint, formatting, type checking, and package importability without rewriting source files or refreshing `uv.lock`. Run `just setup` first so the project environment is available.

The generic `just run <script.py>` task executes only the named Python script. The scaffold intentionally has no application-run or benchmark task until those features are implemented.

## Checks requiring Imman's machine

The automated quality workflow checks the committed environment and source package on a native Windows runner. The environment diagnostic in this checkout validates Quirora's installed Tesseract and local asset paths. Imman should run `just setup`, `just prepare-assets`, `just check-environment`, and `just verify` on his own Windows machine before integration; the local Tesseract install and supplied asset paths cannot be verified by repository CI.
