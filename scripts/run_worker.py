"""Start the distributed OCR worker from its text configuration."""

from __future__ import annotations

import argparse
from pathlib import Path

from parallel_ocr_pipeline.distributed import run_worker


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a Pyro5 OCR worker node.")
    parser.add_argument("config", nargs="?", default="worker_config.txt")
    arguments = parser.parse_args()
    return run_worker(Path(arguments.config))


if __name__ == "__main__":
    raise SystemExit(main())
