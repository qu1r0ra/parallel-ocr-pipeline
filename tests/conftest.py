from __future__ import annotations

import os
import shutil
import subprocess
import sys
import textwrap
import threading
from collections.abc import Callable
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from parallel_ocr_pipeline.recognizer import DEFAULT_TESSDATA_DIR, TesseractRecognizer

SUBPROCESS_LIMIT_SECONDS = 60


class DeterministicRecognizer:
    """Return fixed text for each test image while tracking concurrency and ownership."""

    def __init__(
        self,
        text_by_marker: dict[int, str],
        barrier: threading.Barrier,
        slow_marker: int | None = None,
    ) -> None:
        self._text_by_marker = text_by_marker
        self._barrier = barrier
        self._slow_marker = slow_marker
        self._release_slow = threading.Event()
        self._fast_completions = 0
        self._lock = threading.Lock()
        self._active = 0
        self.max_active = 0
        self.images: list[Image.Image] = []
        self.threads: set[threading.Thread] = set()

    def recognize(self, image: Image.Image, /) -> str:
        with self._lock:
            self._active += 1
            self.max_active = max(self.max_active, self._active)
            self.images.append(image)
            self.threads.add(threading.current_thread())

        try:
            self._barrier.wait(timeout=5)
            pixel = image.getpixel((0, 0))
            if not isinstance(pixel, tuple) or not isinstance(pixel[0], int):
                raise TypeError("Test image did not contain an RGB marker.")
            marker = pixel[0]
            if marker == self._slow_marker:
                if not self._release_slow.wait(timeout=5):
                    raise TimeoutError("Other worker calls did not complete.")
            elif self._slow_marker is not None:
                with self._lock:
                    self._fast_completions += 1
                    if self._fast_completions == self._barrier.parties - 1:
                        self._release_slow.set()
            return self._text_by_marker[marker]
        finally:
            with self._lock:
                self._active -= 1


def write_pipeline_image(path: Path, marker: int) -> Path:
    """Create a tiny image whose first pixel identifies it to the fake recognizer."""
    image = Image.new("RGB", (2, 2), (marker, 0, 0))
    image.save(path)
    image.close()
    return path


@pytest.fixture
def pipeline_image_writer() -> Callable[[Path, int], Path]:
    return write_pipeline_image


@pytest.fixture
def deterministic_recognizer_factory() -> type[DeterministicRecognizer]:
    return DeterministicRecognizer


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
