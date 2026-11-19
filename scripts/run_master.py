"""Start the distributed OCR master from its text configuration."""

from __future__ import annotations

import argparse
from pathlib import Path

from parallel_ocr_pipeline.distributed import run_master


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Pyro5 OCR master.")
    parser.add_argument("config", nargs="?", default="master_config.txt")
    arguments = parser.parse_args()
    return run_master(Path(arguments.config))


if __name__ == "__main__":
    raise SystemExit(main())
