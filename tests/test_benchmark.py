from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from conftest import fake_tesseract

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "scripts" / "benchmark_pipeline.py"


def test_benchmark_stops_and_preserves_artifacts_after_failed_warmup(
    tmp_path: Path,
    pipeline_image_writer: Callable[[Path, int], Path],
) -> None:
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    for index in range(100):
        pipeline_image_writer(image_dir / f"sample-{index:03}.png", index)
    (tmp_path / "config.txt").write_text(
        f"image_dir={image_dir}\nn_workers=2\n",
        encoding="utf-8",
    )
    executable = fake_tesseract(tmp_path, "echo image failed 1>&2\nexit /b 1")
    environment = os.environ.copy()
    environment["TESSERACT_CMD"] = str(executable)

    completed = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 1
    match = re.search(
        r"Temporary artifacts preserved at: (.+)", completed.stderr, flags=re.IGNORECASE
    )
    assert match is not None, completed.stderr
    preserved_directory = Path(match.group(1).strip())
    assert preserved_directory.is_dir()
    assert list(preserved_directory.rglob("ocr_results.partial.csv"))
    assert list(preserved_directory.rglob("ocr_failures.csv"))
    shutil.rmtree(preserved_directory)
