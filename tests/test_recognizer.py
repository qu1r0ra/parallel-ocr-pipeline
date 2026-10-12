from __future__ import annotations

import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from PIL import Image

from conftest import (
    fake_tesseract,
    real_executable,
    render_word,
    requires_real_ocr,
    run_bounded,
)
from parallel_ocr_pipeline.evaluation import normalize
from parallel_ocr_pipeline.recognizer import (
    PrerequisiteError,
    RecognitionFailedError,
    RecognitionTimeoutError,
    TesseractRecognizer,
)

WORDS = ["grape", "window", "stream", "orange", "bridge", "planet", "silver", "market"]


@requires_real_ocr
def test_recognizes_text_in_an_in_memory_image(recognizer: TesseractRecognizer) -> None:
    assert normalize(recognizer.recognize(render_word("window"))) == "window"


@requires_real_ocr
def test_legitimate_empty_result_is_valid_inference(recognizer: TesseractRecognizer) -> None:
    blank = Image.new("RGB", (200, 100), "white")
    assert recognizer.recognize(blank) == ""


@requires_real_ocr
def test_repeat_calls_keep_the_caller_image_open_and_unchanged(
    recognizer: TesseractRecognizer,
) -> None:
    image = render_word("planet").convert("RGBA")
    before = image.tobytes()
    first = recognizer.recognize(image)
    second = recognizer.recognize(image)
    assert first == second
    assert image.mode == "RGBA"
    assert image.tobytes() == before


@requires_real_ocr
def test_concurrent_calls_return_each_callers_own_text(recognizer: TesseractRecognizer) -> None:
    images = {word: render_word(word) for word in WORDS}
    with ThreadPoolExecutor(max_workers=len(WORDS)) as pool:
        futures = {word: pool.submit(recognizer.recognize, image) for word, image in images.items()}
        results = {word: normalize(future.result()) for word, future in futures.items()}
    assert results == {word: word for word in WORDS}


def test_missing_executable_is_a_prerequisite_failure(tmp_path: Path) -> None:
    recognizer = TesseractRecognizer(executable=tmp_path / "no-such-tesseract.exe")
    with pytest.raises(PrerequisiteError, match="not found"):
        recognizer.recognize(render_word("x"))


def test_missing_model_is_a_prerequisite_failure(tmp_path: Path) -> None:
    executable = fake_tesseract(
        tmp_path,
        "echo Error opening data file eng.traineddata 1>&2\n"
        "echo Failed loading language 'eng' 1>&2\n"
        "exit /b 1",
    )
    recognizer = TesseractRecognizer(executable=executable, tessdata_dir=tmp_path)
    with pytest.raises(PrerequisiteError, match="eng"):
        recognizer.recognize(render_word("x"))


def test_image_specific_failure_is_not_a_prerequisite_failure(tmp_path: Path) -> None:
    executable = fake_tesseract(tmp_path, "echo Image too small to scale 1>&2\nexit /b 1")
    recognizer = TesseractRecognizer(executable=executable)
    with pytest.raises(RecognitionFailedError, match="too small"):
        recognizer.recognize(render_word("x"))


def test_failed_attempt_releases_temporary_files_and_keeps_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    executable = fake_tesseract(tmp_path, "exit /b 1")
    recognizer = TesseractRecognizer(executable=executable)
    image = render_word("x")
    with pytest.raises(RecognitionFailedError):
        recognizer.recognize(image)
    assert list(scratch.iterdir()) == []
    assert image.getpixel((0, 0)) == (255, 255, 255)


def test_non_positive_timeout_is_rejected() -> None:
    with pytest.raises(ValueError, match="timeout"):
        TesseractRecognizer(timeout=0)


_TIMEOUT_AND_RETRY_SNIPPET = """
import os
from PIL import Image
from parallel_ocr_pipeline.recognizer import RecognitionTimeoutError, TesseractRecognizer

{setup}
recognizer = TesseractRecognizer(executable={executable!r}, timeout={timeout})
image = Image.new("RGB", (80, 40), "white")
for _ in range(2):
    try:
        recognizer.recognize(image)
    except RecognitionTimeoutError:
        pass
    else:
        raise SystemExit("expected a timeout")
image.getpixel((0, 0))
print("ok")
"""


def test_hung_tesseract_times_out_and_the_same_image_can_be_retried(tmp_path: Path) -> None:
    # A stand-in "tesseract" that hangs at startup: the base interpreter (no child process)
    # picks up a sitecustomize module that sleeps.
    (tmp_path / "sitecustomize.py").write_text("import time\ntime.sleep(60)\n", encoding="utf-8")
    result = run_bounded(
        _TIMEOUT_AND_RETRY_SNIPPET.format(
            setup=f"os.environ['PYTHONPATH'] = {str(tmp_path)!r}",
            executable=sys._base_executable,  # pyright: ignore[reportAttributeAccessIssue]
            timeout=1,
        )
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


@requires_real_ocr
def test_real_tesseract_timeout_is_a_transient_failure_and_retryable() -> None:
    result = run_bounded(
        _TIMEOUT_AND_RETRY_SNIPPET.format(setup="", executable=real_executable(), timeout=0.001)
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_timeout_is_distinguishable_from_prerequisite_failure() -> None:
    assert not issubclass(RecognitionTimeoutError, PrerequisiteError)
    assert not issubclass(RecognitionTimeoutError, RecognitionFailedError)
