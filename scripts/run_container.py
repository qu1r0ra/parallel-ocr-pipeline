"""Create private container config files and start the master or worker application."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from parallel_ocr_pipeline.distributed import run_master, run_worker

MASTER_CONFIG_PATH = Path("/tmp/master_config.txt")
WORKER_CONFIG_PATH = Path("/tmp/worker_config.txt")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("role", choices=("master", "worker"))
    role = parser.parse_args().role

    if role == "master":
        MASTER_CONFIG_PATH.write_text(
            f"image_dir={os.environ.get('IMAGE_DIR', '/data/images')}\n"
            f"port={os.environ.get('MASTER_PORT', '5000')}\n",
            encoding="utf-8",
        )
        return run_master(MASTER_CONFIG_PATH)

    WORKER_CONFIG_PATH.write_text(
        f"master_host={os.environ.get('MASTER_HOST', 'master')}\n"
        f"master_port={os.environ.get('MASTER_PORT', '5000')}\n"
        f"n_workers={os.environ.get('N_WORKERS', '1')}\n",
        encoding="utf-8",
    )
    return run_worker(WORKER_CONFIG_PATH)


if __name__ == "__main__":
    sys.exit(main())
