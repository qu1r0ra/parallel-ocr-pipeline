"""Validate and score a complete pipeline-produced CSV against the supplied labels."""

from __future__ import annotations

import argparse
import csv
import math
import sys
from pathlib import Path

from parallel_ocr_pipeline.evaluation import (
    PASS_THRESHOLD,
    character_accuracy,
    read_labels,
    score,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "local-assets" / "dataset"
EXPECTED_IMAGE_COUNT = 100
RESULT_FIELDS = ["image_id", "filename", "text", "processing_time_ms"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results_csv", type=Path, help="complete ocr_results.csv from the pipeline")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--verbose", action="store_true", help="print every image score")
    arguments = parser.parse_args()

    try:
        labels = read_labels(arguments.dataset / "labels.txt")
        if len(labels) != EXPECTED_IMAGE_COUNT:
            raise ValueError(f"expected {EXPECTED_IMAGE_COUNT} labels, found {len(labels)}")
        expected_names = sorted(labels, key=lambda name: (name.casefold(), name))
        with arguments.results_csv.open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames != RESULT_FIELDS:
                raise ValueError(
                    f"expected CSV fields {RESULT_FIELDS!r}, found {reader.fieldnames!r}"
                )
            raw_rows = list(reader)
        rows: list[dict[str, str]] = []
        for row in raw_rows:
            if None in row:
                raise ValueError("each result row must contain exactly four CSV fields")
            values: dict[str, str] = {}
            for field in RESULT_FIELDS:
                value = row.get(field)
                if value is None:
                    raise ValueError("each result row must contain all four CSV fields")
                values[field] = value
            rows.append(values)

        if len(rows) != EXPECTED_IMAGE_COUNT:
            raise ValueError(f"expected {EXPECTED_IMAGE_COUNT} rows, found {len(rows)}")
        filenames = [row["filename"] for row in rows]
        if len(set(filenames)) != EXPECTED_IMAGE_COUNT or set(filenames) != set(labels):
            raise ValueError("CSV filenames must contain each labelled image exactly once")
        try:
            image_ids = [int(row["image_id"]) for row in rows]
        except (TypeError, ValueError) as error:
            raise ValueError("CSV image IDs must be integers") from error
        expected_by_id = dict(enumerate(expected_names, start=1))
        actual_by_id = dict(zip(image_ids, filenames, strict=True))
        if len(set(image_ids)) != EXPECTED_IMAGE_COUNT or actual_by_id != expected_by_id:
            raise ValueError("IDs must map to the sorted label filenames")

        for row in rows:
            try:
                processing_time_ms = float(row["processing_time_ms"])
            except (TypeError, ValueError) as error:
                raise ValueError("processing times must be numeric") from error
            if not math.isfinite(processing_time_ms) or processing_time_ms < 0:
                raise ValueError("processing times must be finite and nonnegative")
        scores = [score(labels[row["filename"]], row["text"]) for row in rows]
        accuracy = character_accuracy(scores)
        exact_matches = sum(result.distance == 0 for result in scores)
        if arguments.verbose:
            for row, result in zip(rows, scores, strict=True):
                print(f"{row['filename']}  expected={result.expected!r}  actual={result.actual!r}")
        print(f"Images: {len(rows)}  exact matches: {exact_matches}  recognition failures: 0")
        print(f"Character accuracy: {accuracy:.4f} (threshold {PASS_THRESHOLD})")
        if accuracy < PASS_THRESHOLD:
            print(
                f"Pipeline output is below the required threshold of {PASS_THRESHOLD}.",
                file=sys.stderr,
            )
            return 1
    except (OSError, csv.Error, KeyError, ValueError) as error:
        print(f"Cannot evaluate pipeline output: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
