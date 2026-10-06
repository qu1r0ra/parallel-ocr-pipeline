"""The shared image-to-text interface; recognition is implemented in its own ticket."""

from typing import Protocol

from PIL import Image


class ImageRecognizer(Protocol):
    """Recognize text from an already-loaded image owned by the caller."""

    def recognize(self, image: Image.Image, /) -> str:
        """Return extracted text or raise an exception when recognition fails."""
        ...
