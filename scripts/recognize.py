"""Recognize text in one image with the real Tesseract recognizer (development command)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image

from parallel_ocr_pipeline.recognizer import (
    DEFAULT_TESSDATA_DIR,
    DEFAULT_TIMEOUT_SECONDS,
    RecognitionError,
    TesseractRecognizer,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path, help="path to an image file")
    parser.add_argument("--tessdata-dir", type=Path, default=DEFAULT_TESSDATA_DIR)
    parser.add_argument("--executable", help="tesseract.exe path (default: TESSERACT_CMD or PATH)")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    arguments = parser.parse_args()

    recognizer = TesseractRecognizer(
        tessdata_dir=arguments.tessdata_dir,
        executable=arguments.executable,
        timeout=arguments.timeout,
    )
    try:
        with Image.open(arguments.image) as opened:
            opened.load()
            image = opened.copy()
        try:
            print(recognizer.recognize(image))
        finally:
            image.close()
    except (OSError, RecognitionError) as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
