from __future__ import annotations

import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from parallel_ocr_pipeline.recognizer import DEFAULT_TESSDATA_DIR, TesseractRecognizer

SUBPROCESS_LIMIT_SECONDS = 60


def real_executable() -> str | None:
    return os.environ.get("TESSERACT_CMD") or shutil.which("tesseract")


requires_real_ocr = pytest.mark.skipif(
    real_executable() is None or not (DEFAULT_TESSDATA_DIR / "eng.traineddata").is_file(),
    reason="real Tesseract and the supplied eng.traineddata are required",
)


def render_word(word: str) -> Image.Image:
    font = ImageFont.load_default(size=48)
    image = Image.new("RGB", (60 + 32 * len(word), 100), "white")
    ImageDraw.Draw(image).text((20, 20), word, fill="black", font=font)
    return image


def fake_tesseract(directory: Path, body: str) -> Path:
    """Create a fake tesseract.cmd running ``body`` (cmd.exe batch lines)."""
    script = directory / "fake-tesseract.cmd"
    script.write_text("@echo off\r\n" + body.replace("\n", "\r\n") + "\r\n", encoding="ascii")
    return script


def run_bounded(code: str) -> subprocess.CompletedProcess[str]:
    """Run ``code`` in a fresh interpreter that is killed if it hangs."""
    return subprocess.run(
        [sys.executable, "-I", "-c", textwrap.dedent(code)],
        capture_output=True,
        text=True,
        timeout=SUBPROCESS_LIMIT_SECONDS,
        check=False,
    )


@pytest.fixture
def recognizer() -> TesseractRecognizer:
    return TesseractRecognizer(executable=real_executable())
