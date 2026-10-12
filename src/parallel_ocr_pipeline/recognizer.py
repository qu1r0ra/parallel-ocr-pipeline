"""Tesseract-backed image recognition with explicit, caller-visible failures."""

from __future__ import annotations

import os
import threading
from pathlib import Path

import pytesseract
from PIL import Image, ImageFilter, ImageOps

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TESSDATA_DIR = PROJECT_ROOT / "local-assets" / "models"
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_LANGUAGE = "eng"
MEDIAN_FILTER_SIZE = 3
BORDER_PIXELS = 20
_PYTESSERACT_TIMEOUT_MESSAGE = "Tesseract process timeout"
_MODEL_FAILURE_MARKERS = (
    "Error opening data file",
    "Failed loading language",
    "Could not initialize tesseract",
)

_configuration_lock = threading.Lock()


class RecognitionError(Exception):
    """A recognition attempt failed; the pipeline decides whether to retry."""


class RecognitionTimeoutError(RecognitionError):
    """Tesseract exceeded its time limit on one image; a retry may succeed."""


class RecognitionFailedError(RecognitionError):
    """Tesseract rejected or failed on this image; retrying is not expected to help."""


class PrerequisiteError(RecognitionError):
    """The executable or model is unavailable; every image will fail the same way."""


def preprocess(image: Image.Image) -> Image.Image:
    """Return a new image prepared for Tesseract; the input is left untouched.

    The dataset is dark text on a light background with speckle noise. Flattening to grayscale
    (compositing any alpha onto white), median-filtering the specks, stretching contrast, and
    adding a white border gave the best character accuracy in the evaluation recorded in
    ``docs/ocr-evaluation.md``.
    """
    derived: list[Image.Image] = []
    try:
        flattened = _flatten_to_gray(image)
        derived.append(flattened)
        denoised = flattened.filter(ImageFilter.MedianFilter(MEDIAN_FILTER_SIZE))
        derived.append(denoised)
        stretched = ImageOps.autocontrast(denoised, cutoff=1)
        derived.append(stretched)
        return ImageOps.expand(stretched, BORDER_PIXELS, fill=255)
    finally:
        for temporary in derived:
            temporary.close()


def _flatten_to_gray(image: Image.Image) -> Image.Image:
    if "A" in image.getbands():
        background = Image.new("RGBA", image.size, (255, 255, 255, 255))
        composited = Image.alpha_composite(background, image.convert("RGBA"))
        try:
            return composited.convert("L")
        finally:
            background.close()
            composited.close()
    return image.convert("L")


class TesseractRecognizer:
    """Recognize text in caller-owned images; safe to call from several threads.

    The recognizer neither closes nor mutates the image it is given. It creates and releases its
    own derived images on every call, and each call runs an independent Tesseract process.

    ``pytesseract`` reads the executable from a module attribute and the model directory from the
    ``TESSDATA_PREFIX`` environment variable, so ``executable`` and ``tessdata_dir`` are
    process-wide settings applied at construction; the most recently built recognizer's values
    apply. ``TESSDATA_PREFIX`` is used because ``pytesseract`` cannot pass a quoted
    ``--tessdata-dir`` containing spaces on Windows.
    """

    def __init__(
        self,
        *,
        tessdata_dir: str | os.PathLike[str] = DEFAULT_TESSDATA_DIR,
        executable: str | os.PathLike[str] | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        language: str = DEFAULT_LANGUAGE,
    ) -> None:
        """Configure a recognizer.

        ``executable`` defaults to ``TESSERACT_CMD`` when set, otherwise ``tesseract`` on
        ``PATH``. ``timeout`` is the finite per-attempt limit in seconds.
        """
        if timeout <= 0:
            raise ValueError("timeout must be a positive number of seconds")
        self._timeout = timeout
        self._language = language
        self._tessdata_dir = Path(tessdata_dir).resolve()
        chosen = executable if executable is not None else os.environ.get("TESSERACT_CMD")
        self._executable = os.fspath(chosen) if chosen else "tesseract"
        with _configuration_lock:
            pytesseract.pytesseract.tesseract_cmd = self._executable
            os.environ["TESSDATA_PREFIX"] = str(self._tessdata_dir)

    def recognize(self, image: Image.Image, /) -> str:
        """Return the text found in ``image``, which may legitimately be empty.

        Raises ``RecognitionTimeoutError`` for a transient time-out, ``PrerequisiteError`` when
        the executable or model is missing, and ``RecognitionFailedError`` for other failures.
        """
        prepared = preprocess(image)
        try:
            return self._run_tesseract(prepared)
        finally:
            prepared.close()

    def _run_tesseract(self, prepared: Image.Image) -> str:
        try:
            # pytesseract annotates timeout as int but forwards it to Popen.communicate (floats ok).
            text = pytesseract.image_to_string(
                prepared,
                lang=self._language,
                timeout=self._timeout,  # pyright: ignore[reportArgumentType]
            )
        except pytesseract.TesseractNotFoundError as error:
            raise PrerequisiteError(
                f"Tesseract executable not found: {self._executable!r}"
            ) from error
        except pytesseract.TesseractError as error:
            message = str(error.message)
            if any(marker in message for marker in _MODEL_FAILURE_MARKERS):
                raise PrerequisiteError(
                    f"Tesseract could not load model {self._language!r} from "
                    f"{self._tessdata_dir}: {message}"
                ) from error
            raise RecognitionFailedError(
                f"Tesseract exited with status {error.status}: {message}"
            ) from error
        except OSError as error:
            # Not a missing executable: may be temp-file I/O for this image, so stay per-image.
            raise RecognitionFailedError(
                f"Tesseract could not run on this image: {error}"
            ) from error
        except RuntimeError as error:
            if str(error) == _PYTESSERACT_TIMEOUT_MESSAGE:
                raise RecognitionTimeoutError(
                    f"Tesseract exceeded {self._timeout} seconds"
                ) from error
            raise RecognitionFailedError(f"Tesseract failed: {error}") from error
        return text.strip()
