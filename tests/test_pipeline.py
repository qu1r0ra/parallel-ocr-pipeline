from __future__ import annotations

import csv
import threading
from collections.abc import Callable
from pathlib import Path

import pytest
from PIL import Image

from conftest import DeterministicRecognizer
from parallel_ocr_pipeline.pipeline import run


@pytest.mark.parametrize("n_workers", [1, 3])
def test_run_writes_associated_csv_rows_and_closes_images_and_threads(
    tmp_path: Path,
    n_workers: int,
    pipeline_image_writer: Callable[[Path, int], Path],
    deterministic_recognizer_factory: type[DeterministicRecognizer],
) -> None:
    """Write one escaped, correctly identified result per image and join all threads."""
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    names_and_markers = [("charlie.png", 3), ("alpha.png", 1), ("bravo.png", 2)]
    for filename, marker in names_and_markers:
        pipeline_image_writer(image_dir / filename, marker)

    config_path = tmp_path / "config.txt"
    config_path.write_text(f"image_dir={image_dir}\nn_workers={n_workers}\n", encoding="utf-8")
    expected_text = {
        1: 'comma, quote " and\nnewline',
        2: "second image",
        3: "third image",
    }
    recognizer = deterministic_recognizer_factory(
        expected_text,
        threading.Barrier(n_workers),
        slow_marker=1 if n_workers > 1 else None,
    )

    assert run(config_path, recognizer) == 0

    with (tmp_path / "ocr_results.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))

    row_ids = [row["image_id"] for row in rows]
    assert len(row_ids) == 3
    assert len(set(row_ids)) == 3
    assert {row["image_id"] for row in rows} == {"1", "2", "3"}
    if n_workers > 1:
        assert row_ids != ["1", "2", "3"]
    assert {row["filename"]: row["text"] for row in rows} == {
        "alpha.png": expected_text[1],
        "bravo.png": expected_text[2],
        "charlie.png": expected_text[3],
    }
    assert all(float(row["processing_time_ms"]) >= 0 for row in rows)
    assert len(recognizer.threads) == n_workers
    assert all(not thread.is_alive() for thread in recognizer.threads)
    assert all(_is_closed(image) for image in recognizer.images)
    assert recognizer.max_active == n_workers
    assert not list(tmp_path.glob(".ocr_results.*.tmp"))


def _is_closed(image: Image.Image) -> bool:
    with pytest.raises(ValueError):
        image.getpixel((0, 0))
    return True
