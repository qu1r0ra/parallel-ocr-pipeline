"""Run the configured multi-worker OCR pipeline."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from parallel_ocr_pipeline.config import ConfigError
from parallel_ocr_pipeline.pipeline import run


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "config",
        nargs="?",
        type=Path,
        default=Path("config.txt"),
        help="pipeline configuration file (default: config.txt)",
    )
    arguments = parser.parse_args(argv)

    try:
        return run(arguments.config)
    except ConfigError as error:
        print(f"ConfigError: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
