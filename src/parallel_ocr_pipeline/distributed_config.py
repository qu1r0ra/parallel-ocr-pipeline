"""Separate master and worker configuration for the distributed OCR application."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_MASTER_KEYS = frozenset({"image_dir", "port"})
_WORKER_KEYS = frozenset({"master_host", "master_port", "n_workers"})
_POSITIVE_INTEGER = re.compile(r"[0-9]+\Z")
MAX_WORKERS_PER_NODE = 32


class DistributedConfigError(ValueError):
    """The distributed master or worker configuration is invalid."""


@dataclass(frozen=True, slots=True)
class MasterConfig:
    """Validated master settings and paths derived from its config file."""

    image_dir: Path
    port: int
    output_dir: Path


@dataclass(frozen=True, slots=True)
class WorkerConfig:
    """Validated worker connection and process-count settings."""

    master_host: str
    master_port: int
    n_workers: int


def load_master_config(config_path: str | Path) -> MasterConfig:
    """Read image_dir and port, resolving relative image paths beside the config."""
    source, values = _read_values(config_path, _MASTER_KEYS)
    image_dir = Path(values["image_dir"]).expanduser()
    if not image_dir.is_absolute():
        image_dir = source.parent / image_dir
    image_dir = image_dir.resolve()
    if not image_dir.exists():
        raise DistributedConfigError(f"Image directory does not exist: {image_dir}.")
    if not image_dir.is_dir():
        raise DistributedConfigError(f"Image path is not a directory: {image_dir}.")

    return MasterConfig(
        image_dir=image_dir,
        port=_parse_port(values["port"], "port"),
        output_dir=source.parent,
    )


def load_worker_config(config_path: str | Path) -> WorkerConfig:
    """Read master_host, master_port, and the per-node worker process count."""
    _, values = _read_values(config_path, _WORKER_KEYS)
    host = values["master_host"]
    if any(character.isspace() for character in host):
        raise DistributedConfigError("master_host must not contain whitespace.")

    worker_count_value = values["n_workers"]
    if not _POSITIVE_INTEGER.fullmatch(worker_count_value):
        raise DistributedConfigError(
            f"n_workers must be a positive integer, got {worker_count_value!r}."
        )
    worker_count = int(worker_count_value)
    if worker_count < 1:
        raise DistributedConfigError(
            f"n_workers must be a positive integer, got {worker_count_value!r}."
        )
    if worker_count > MAX_WORKERS_PER_NODE:
        raise DistributedConfigError(
            f"n_workers must not exceed {MAX_WORKERS_PER_NODE} on one worker node."
        )

    return WorkerConfig(
        master_host=host,
        master_port=_parse_port(values["master_port"], "master_port"),
        n_workers=worker_count,
    )


def _read_values(
    config_path: str | Path, required_keys: frozenset[str]
) -> tuple[Path, dict[str, str]]:
    source = Path(config_path).expanduser().resolve()
    try:
        contents = source.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as error:
        raise DistributedConfigError(f"Cannot read config file {source}: {error}") from error

    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(contents.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise DistributedConfigError(
                f"Invalid config line {line_number} in {source}: expected key=value."
            )
        key, value = (part.strip() for part in line.split("=", maxsplit=1))
        if not key or not value:
            raise DistributedConfigError(
                f"Invalid config line {line_number} in {source}: key and value are required."
            )
        if key not in required_keys:
            raise DistributedConfigError(
                f"Unknown config key {key!r} on line {line_number} in {source}."
            )
        if key in values:
            raise DistributedConfigError(
                f"Duplicate config key {key!r} on line {line_number} in {source}."
            )
        values[key] = value

    missing = sorted(required_keys - values.keys())
    if missing:
        raise DistributedConfigError(f"Missing required config setting(s): {', '.join(missing)}.")
    return source, values


def _parse_port(value: str, setting: str) -> int:
    if not _POSITIVE_INTEGER.fullmatch(value):
        raise DistributedConfigError(f"{setting} must be an integer, got {value!r}.")
    port = int(value)
    if not 1 <= port <= 65535:
        raise DistributedConfigError(f"{setting} must be between 1 and 65535, got {value!r}.")
    return port
