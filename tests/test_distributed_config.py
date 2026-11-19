from __future__ import annotations

from pathlib import Path

import pytest

from parallel_ocr_pipeline.distributed_config import (
    DistributedConfigError,
    load_master_config,
    load_worker_config,
)


def test_load_master_config_resolves_image_dir_from_config_and_keeps_output_beside_config(
    tmp_path: Path,
) -> None:
    images = tmp_path / "assets" / "images"
    images.mkdir(parents=True)
    config = tmp_path / "master_config.txt"
    config.write_text("image_dir=assets/images\nport=5012\n", encoding="utf-8")

    loaded = load_master_config(config)

    assert loaded.image_dir == images.resolve()
    assert loaded.port == 5012
    assert loaded.output_dir == tmp_path.resolve()


@pytest.mark.parametrize(
    ("contents", "message"),
    [
        ("image_dir=images\n", "Missing required config setting"),
        ("image_dir=images\nport=abc\n", "port must be an integer"),
        ("image_dir=images\nport=0\n", "port must be between"),
        ("image_dir=images\nport=65536\n", "port must be between"),
        ("image_dir=images\nport=5000\nport=5001\n", "Duplicate config key"),
        ("image_dir=images\nport=5000\nextra=x\n", "Unknown config key"),
    ],
)
def test_load_master_config_rejects_invalid_settings(
    tmp_path: Path, contents: str, message: str
) -> None:
    (tmp_path / "images").mkdir()
    config = tmp_path / "master_config.txt"
    config.write_text(contents, encoding="utf-8")

    with pytest.raises(DistributedConfigError, match=message):
        load_master_config(config)


def test_load_master_config_rejects_missing_image_directory(tmp_path: Path) -> None:
    config = tmp_path / "master_config.txt"
    config.write_text("image_dir=missing\nport=5000\n", encoding="utf-8")

    with pytest.raises(DistributedConfigError, match="Image directory does not exist"):
        load_master_config(config)


def test_load_worker_config_reads_all_handout_settings(tmp_path: Path) -> None:
    config = tmp_path / "worker_config.txt"
    config.write_text(
        "master_host=127.0.0.1\nmaster_port=5000\nn_workers=2\n",
        encoding="utf-8",
    )

    loaded = load_worker_config(config)

    assert loaded.master_host == "127.0.0.1"
    assert loaded.master_port == 5000
    assert loaded.n_workers == 2


@pytest.mark.parametrize(
    ("contents", "message"),
    [
        ("master_host=localhost\nmaster_port=5000\n", "Missing required config setting"),
        ("master_host=localhost\nmaster_port=0\nn_workers=1\n", "master_port must be between"),
        (
            "master_host=localhost\nmaster_port=5000\nn_workers=0\n",
            "n_workers must be a positive integer",
        ),
        ("master_host=\nmaster_port=5000\nn_workers=1\n", "key and value are required"),
        ("master_host=localhost\nmaster_port=5000\nn_workers=1\nextra=x\n", "Unknown config key"),
    ],
)
def test_load_worker_config_rejects_invalid_settings(
    tmp_path: Path, contents: str, message: str
) -> None:
    config = tmp_path / "worker_config.txt"
    config.write_text(contents, encoding="utf-8")

    with pytest.raises(DistributedConfigError, match=message):
        load_worker_config(config)
