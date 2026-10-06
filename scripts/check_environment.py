"""Report whether the local Windows OCR prerequisites are available."""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from asset_contract import EXPECTED_IMAGE_NAMES

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCAL_ASSETS = PROJECT_ROOT / "local-assets"
ARCHIVE = LOCAL_ASSETS / "supplied" / "dataset.zip"
MODEL_DIRECTORY = LOCAL_ASSETS / "models"
MODEL_FILE = MODEL_DIRECTORY / "eng.traineddata"
IMAGE_DIRECTORY = LOCAL_ASSETS / "dataset" / "images"
LABELS_FILE = LOCAL_ASSETS / "dataset" / "labels.txt"


def _report(ok: bool, message: str) -> bool:
    print(f"[{'OK' if ok else 'MISSING'}] {message}")
    return ok


def _tesseract_path() -> Path | None:
    configured = os.environ.get("TESSERACT_CMD")
    if configured:
        candidate = Path(configured).expanduser()
        return candidate if candidate.is_file() else None
    found = shutil.which("tesseract")
    return Path(found) if found else None


def _check_model(executable: Path) -> bool:
    try:
        with tempfile.TemporaryDirectory(prefix="parallel-ocr-model-check-") as temp_directory:
            probe_image = Path(temp_directory) / "probe.ppm"
            probe_image.write_bytes(b"P6\n100 100\n255\n" + bytes([255]) * 30_000)
            result = subprocess.run(
                [
                    str(executable),
                    str(probe_image),
                    "stdout",
                    "--tessdata-dir",
                    str(MODEL_DIRECTORY),
                    "-l",
                    "eng",
                ],
                capture_output=True,
                check=False,
                text=True,
                timeout=15,
            )
    except (OSError, subprocess.TimeoutExpired) as error:
        return _report(False, f"Could not initialize the supplied English model: {error}")

    if result.returncode == 0:
        return _report(
            True,
            f"Tesseract initialized and ran with the supplied model in {MODEL_DIRECTORY}.",
        )

    detail = result.stderr.strip() or result.stdout.strip() or "no diagnostic output was returned"
    return _report(False, f"Tesseract could not initialize the supplied English model: {detail}")


def _check_dataset() -> bool:
    ok = True
    ok &= _report(ARCHIVE.is_file(), f"Dataset archive present at {ARCHIVE}.")
    if not ARCHIVE.is_file():
        print(
            "       Copy the supplied dataset.zip to local-assets/supplied/ and rerun just prepare-assets."
        )

    image_names = {path.name for path in IMAGE_DIRECTORY.glob("*.png")}
    complete = image_names == EXPECTED_IMAGE_NAMES and LABELS_FILE.is_file()
    ok &= _report(
        complete, f"Prepared 100 images and separate labels under {LOCAL_ASSETS / 'dataset'}."
    )
    if not complete:
        print(
            "       Run `just prepare-assets` after placing dataset.zip in local-assets/supplied/."
        )
    return ok


def main() -> int:
    errors = 0
    errors += not _report(
        sys.version_info[:2] == (3, 11),
        f"Python 3.11 selected (running {sys.version.split()[0]}).",
    )
    if sys.version_info[:2] != (3, 11):
        print("       Run `just setup` to install and select the pinned Python 3.11 environment.")

    for module, package in (("PIL", "Pillow"), ("pytesseract", "pytesseract")):
        available = importlib.util.find_spec(module) is not None
        errors += not _report(available, f"Python package {package} is installed.")
        if not available:
            print("       Run `just setup` to install locked project dependencies.")

    model_available = _report(MODEL_FILE.is_file(), f"English model file present at {MODEL_FILE}.")
    errors += not model_available
    if not model_available:
        print("       Copy the supplied eng.traineddata to local-assets/models/eng.traineddata.")

    executable = _tesseract_path()
    errors += not _report(executable is not None, "Tesseract executable is available.")
    if executable is None:
        print(
            "       Install the Windows Tesseract executable and add its folder to PATH, "
            "or set TESSERACT_CMD to the full tesseract.exe path."
        )
    else:
        try:
            result = subprocess.run(
                [str(executable), "--version"],
                capture_output=True,
                check=False,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            errors += not _report(False, f"Tesseract did not start: {error}")
        else:
            version = result.stdout.splitlines()[0] if result.stdout else ""
            errors += not _report(
                result.returncode == 0, f"{version or 'Tesseract version check'}."
            )
            if result.returncode == 0 and model_available:
                errors += not _check_model(executable)

    errors += not _check_dataset()
    if errors:
        print(f"Environment check found {errors} issue(s).")
        return 1

    print("Environment check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
