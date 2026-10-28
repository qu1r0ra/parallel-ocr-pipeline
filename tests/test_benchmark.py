from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

from conftest import fake_tesseract

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "scripts" / "benchmark_pipeline.py"


def _load_benchmark_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("parallel_ocr_benchmark_pipeline", SCRIPT)
    if spec is None or spec.loader is None:
        raise AssertionError("Could not load the benchmark script as a module.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_benchmark_reports_retry_activity_for_each_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The benchmark CLI includes loader and recognition recoveries for each run."""
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    for index in range(100):
        (image_dir / f"sample-{index:03}.png").touch()
    (tmp_path / "config.txt").write_text(
        f"image_dir={image_dir}\nn_workers=1\n",
        encoding="utf-8",
    )
    benchmark = _load_benchmark_module()
    fake_pipeline = tmp_path / "fake_pipeline.py"
    fake_pipeline.write_text(
        "import csv\n"
        "import sys\n"
        "from pathlib import Path\n"
        "config = Path(sys.argv[1])\n"
        "with (config.parent / 'ocr_results.csv').open('w', encoding='utf-8', newline='') as stream:\n"
        "    writer = csv.writer(stream)\n"
        "    writer.writerow(['image_id', 'filename', 'text', 'processing_time_ms'])\n"
        "    writer.writerows((index, f'image-{index}.png', 'text', 0) for index in range(100))\n"
        "print('Total processing time: 1.250 seconds')\n"
        "print('Recovery activity: loader retries=2, recognition retries=3')\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(benchmark, "_PIPELINE_SCRIPT", fake_pipeline)
    monkeypatch.setattr(benchmark, "WORKER_COUNTS", (1,))
    monkeypatch.setattr(benchmark, "WARMUP_RUNS", 1)
    monkeypatch.setattr(benchmark, "MEASURED_RUNS", 1)

    assert benchmark.main() == 0

    output = capsys.readouterr().out
    assert "Completed warmup 1/1 with 1 worker(s): 1.250 seconds" in output
    assert "Completed measured trial 1/1 with 1 worker(s): 1.250 seconds" in output
    assert output.count("retries: loader=2, recognition=3") == 2
    assert "Successful retries per measured run (loader/recognition): 2/3" in output


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
