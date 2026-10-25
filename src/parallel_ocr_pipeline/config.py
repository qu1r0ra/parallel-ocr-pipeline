"""Configuration and deterministic input discovery for the OCR pipeline."""

from __future__ import annotations

import re
import stat
from dataclasses import dataclass
from pathlib import Path

IMAGE_SUFFIXES = frozenset({".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"})
_CONFIG_KEYS = frozenset({"image_dir", "n_workers"})
_POSITIVE_INTEGER = re.compile(r"[0-9]+\Z")


class ConfigError(ValueError):
    """The pipeline configuration or input image directory is invalid."""


@dataclass(frozen=True, slots=True)
class PipelineConfig:
    """Validated settings read from a pipeline config file."""

    image_dir: Path
    n_workers: int


@dataclass(frozen=True, slots=True)
class InputImage:
    """An input image with an identity fixed before concurrent processing."""

    image_id: int
    path: Path


def load_config(config_path: str | Path) -> PipelineConfig:
    """Read and validate the required image directory and worker count."""
    source = Path(config_path).expanduser().resolve()
    try:
        contents = source.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as error:
        raise ConfigError(f"Cannot read config file {source}: {error}") from error

    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(contents.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ConfigError(f"Invalid config line {line_number} in {source}: expected key=value.")

        key, value = (part.strip() for part in line.split("=", maxsplit=1))
        if not key or not value:
            raise ConfigError(
                f"Invalid config line {line_number} in {source}: key and value are required."
            )
        if key not in _CONFIG_KEYS:
            raise ConfigError(f"Unknown config key {key!r} on line {line_number} in {source}.")
        if key in values:
            raise ConfigError(f"Duplicate config key {key!r} on line {line_number} in {source}.")
        values[key] = value

    missing = sorted(_CONFIG_KEYS - values.keys())
    if missing:
        raise ConfigError(f"Missing required config setting(s): {', '.join(missing)}.")

    worker_value = values["n_workers"]
    if not _POSITIVE_INTEGER.fullmatch(worker_value):
        raise ConfigError(f"n_workers must be a positive integer, got {worker_value!r}.")
    n_workers = int(worker_value)
    if n_workers < 1:
        raise ConfigError(f"n_workers must be a positive integer, got {n_workers}.")

    image_dir = Path(values["image_dir"]).expanduser()
    if not image_dir.is_absolute():
        image_dir = source.parent / image_dir
    image_dir = image_dir.resolve()
    if not image_dir.exists():
        raise ConfigError(f"Image directory does not exist: {image_dir}.")
    if not image_dir.is_dir():
        raise ConfigError(f"Image path is not a directory: {image_dir}.")

    return PipelineConfig(image_dir=image_dir, n_workers=n_workers)


def enumerate_images(image_dir: str | Path) -> tuple[InputImage, ...]:
    """Return supported direct-child images in deterministic order with stable IDs."""
    directory = Path(image_dir).expanduser().resolve()
    if not directory.exists():
        raise ConfigError(f"Image directory does not exist: {directory}.")
    if not directory.is_dir():
        raise ConfigError(f"Image path is not a directory: {directory}.")

    try:
        candidates = [
            entry
            for entry in directory.iterdir()
            if entry.is_file()
            and entry.suffix.casefold() in IMAGE_SUFFIXES
            and not _is_hidden(entry)
        ]
    except OSError as error:
        raise ConfigError(f"Cannot enumerate image directory {directory}: {error}") from error

    candidates.sort(key=lambda path: (path.name.casefold(), path.name))
    if not candidates:
        raise ConfigError(f"No supported images found in {directory}.")

    return tuple(InputImage(image_id=index, path=path) for index, path in enumerate(candidates, 1))


def _is_hidden(path: Path) -> bool:
    if path.name.startswith("."):
        return True
    hidden_attribute = getattr(stat, "FILE_ATTRIBUTE_HIDDEN", 0)
    file_attributes = getattr(path.stat(), "st_file_attributes", 0)
    return bool(hidden_attribute and file_attributes & hidden_attribute)
