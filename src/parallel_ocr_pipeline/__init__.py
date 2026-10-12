"""Interfaces and OCR recognition for the parallel OCR course project."""

from parallel_ocr_pipeline.contracts import ImageRecognizer
from parallel_ocr_pipeline.recognizer import (
    PrerequisiteError,
    RecognitionError,
    RecognitionFailedError,
    RecognitionTimeoutError,
    TesseractRecognizer,
)

__all__ = [
    "ImageRecognizer",
    "PrerequisiteError",
    "RecognitionError",
    "RecognitionFailedError",
    "RecognitionTimeoutError",
    "TesseractRecognizer",
]
