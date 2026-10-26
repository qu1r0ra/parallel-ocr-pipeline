from __future__ import annotations

import csv
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from conftest import fake_tesseract

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "scripts" / "run_pipeline.py"


def test_cli_help_describes_config_argument(tmp_path: Path) -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert completed.returncode == 0
    assert "config" in completed.stdout.casefold()
    assert completed.stderr == ""


def test_cli_reports_invalid_config_with_status_two(tmp_path: Path) -> None:
    config_path = tmp_path / "bad-config.txt"
    config_path.write_text("n_workers=0\n", encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, str(SCRIPT), str(config_path)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert completed.returncode == 2
    assert "ConfigError:" in completed.stderr
    assert "Missing required config setting" in completed.stderr
    assert not (tmp_path / "ocr_results.csv").exists()


@pytest.mark.skipif(os.name != "nt", reason="the fake Tesseract executable is a Windows .cmd file")
@pytest.mark.parametrize(("native_limit", "expected_limit"), [(None, "1"), ("3", "3")])
def test_cli_runs_default_config_with_native_thread_default_or_explicit_override(
    tmp_path: Path,
    pipeline_image_writer: Callable[[Path, int], Path],
    monkeypatch: pytest.MonkeyPatch,
    native_limit: str | None,
    expected_limit: str,
) -> None:
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    pipeline_image_writer(image_dir / "sample.png", 1)
    (tmp_path / "config.txt").write_text(
        f"image_dir={image_dir}\nn_workers=1\n",
        encoding="utf-8",
    )
    executable = fake_tesseract(tmp_path, '> "%~2.txt" echo native threads=%OMP_THREAD_LIMIT%')
    monkeypatch.setenv("TESSERACT_CMD", str(executable))
    if native_limit is None:
        monkeypatch.delenv("OMP_THREAD_LIMIT", raising=False)
    else:
        monkeypatch.setenv("OMP_THREAD_LIMIT", native_limit)

    completed = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    with (tmp_path / "ocr_results.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert [(row["image_id"], row["filename"], row["text"]) for row in rows] == [
        ("1", "sample.png", f"native threads={expected_limit}")
    ]
