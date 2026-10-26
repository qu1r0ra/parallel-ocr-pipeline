from __future__ import annotations

import csv
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "evaluate_pipeline.py"
FIELDS = ["image_id", "filename", "text", "processing_time_ms"]


def _write_dataset(dataset: Path) -> list[str]:
    dataset.mkdir()
    filenames = [f"img{image_id:04}.png" for image_id in range(1, 101)]
    with (dataset / "labels.txt").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["filename", "word"])
        writer.writerows((filename, "parallel") for filename in filenames)
    return filenames


def _write_results(path: Path, filenames: list[str], mode: str) -> None:
    rows = [
        {
            "image_id": str(image_id),
            "filename": filename,
            "text": "parallel" if mode != "low_accuracy" else "",
            "processing_time_ms": "1.25",
        }
        for image_id, filename in enumerate(filenames, start=1)
    ]
    if mode == "partial":
        rows.pop()
    elif mode == "duplicate_id":
        rows[-1]["image_id"] = "1"
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(reversed(rows))


def _run_evaluator(csv_path: Path, dataset: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(csv_path), "--dataset", str(dataset)],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )


def test_cli_scores_complete_pipeline_csv_independent_of_completion_order(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "dataset"
    filenames = _write_dataset(dataset)
    results = tmp_path / "ocr_results.csv"
    _write_results(results, filenames, "valid")

    completed = _run_evaluator(results, dataset)

    assert completed.returncode == 0, completed.stderr
    assert "Images: 100  exact matches: 100" in completed.stdout
    assert "Character accuracy: 1.0000 (threshold 0.5)" in completed.stdout


@pytest.mark.parametrize(
    ("mode", "expected_status", "expected_message"),
    [
        ("partial", 2, "expected 100 rows"),
        ("duplicate_id", 2, "IDs must map to the sorted label filenames"),
        ("low_accuracy", 1, "below the required threshold"),
    ],
)
def test_cli_rejects_incomplete_misassociated_or_low_accuracy_pipeline_results(
    tmp_path: Path,
    mode: str,
    expected_status: int,
    expected_message: str,
) -> None:
    dataset = tmp_path / "dataset"
    filenames = _write_dataset(dataset)
    results = tmp_path / "ocr_results.csv"
    _write_results(results, filenames, mode)

    completed = _run_evaluator(results, dataset)

    assert completed.returncode == expected_status
    assert expected_message in completed.stderr
