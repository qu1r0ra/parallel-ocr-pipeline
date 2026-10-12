"""Evaluate real OCR on the supplied dataset against filename-to-word labels (development)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image

from parallel_ocr_pipeline.evaluation import (
    PASS_THRESHOLD,
    Score,
    character_accuracy,
    read_labels,
    score,
)
from parallel_ocr_pipeline.recognizer import (
    DEFAULT_TESSDATA_DIR,
    DEFAULT_TIMEOUT_SECONDS,
    PrerequisiteError,
    RecognitionError,
    TesseractRecognizer,
)

EXPECTED_IMAGE_COUNT = 100
DATASET = Path(__file__).resolve().parents[1] / "local-assets" / "dataset"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument("--tessdata-dir", type=Path, default=DEFAULT_TESSDATA_DIR)
    parser.add_argument("--executable", help="tesseract.exe path (default: TESSERACT_CMD or PATH)")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--verbose", action="store_true", help="print every image")
    arguments = parser.parse_args()

    labels = read_labels(arguments.dataset / "labels.txt")
    missing = [name for name in labels if not (arguments.dataset / "images" / name).is_file()]
    if len(labels) != EXPECTED_IMAGE_COUNT or missing:
        print(
            f"Cannot evaluate: expected {EXPECTED_IMAGE_COUNT} labelled images, found "
            f"{len(labels)} labels and {len(missing)} missing image files.",
            file=sys.stderr,
        )
        return 2
    recognizer = TesseractRecognizer(
        tessdata_dir=arguments.tessdata_dir,
        executable=arguments.executable,
        timeout=arguments.timeout,
    )

    scores: list[Score] = []
    failures: list[str] = []
    for filename, label in labels.items():
        # Only the image reaches the recognizer; the label is used afterwards for scoring.
        with Image.open(arguments.dataset / "images" / filename) as opened:
            opened.load()
            image = opened.copy()
        try:
            prediction = recognizer.recognize(image)
        except PrerequisiteError as error:
            print(f"Cannot evaluate: {error}", file=sys.stderr)
            return 2
        except RecognitionError as error:
            failures.append(f"{filename}: {type(error).__name__}: {error}")
            prediction = ""
        finally:
            image.close()
        result = score(label, prediction)
        scores.append(result)
        if arguments.verbose or result.distance:
            print(f"{filename}  expected={result.expected!r}  actual={result.actual!r}")

    accuracy = character_accuracy(scores)
    exact = sum(item.distance == 0 for item in scores)
    print(f"\nImages: {len(scores)}  exact matches: {exact}  recognition failures: {len(failures)}")
    for line in failures:
        print(f"  {line}")
    print(f"Character accuracy: {accuracy:.4f} (threshold {PASS_THRESHOLD})")
    return 0 if accuracy >= PASS_THRESHOLD and not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
