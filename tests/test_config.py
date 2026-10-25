from __future__ import annotations

from pathlib import Path

import pytest

from parallel_ocr_pipeline.config import ConfigError, InputImage, enumerate_images, load_config


def write_config(path: Path, image_dir: str, n_workers: str = "2") -> Path:
    """Write the two required settings to a temporary config file."""
    path.write_text(f"image_dir={image_dir}\nn_workers={n_workers}\n", encoding="utf-8")
    return path


def test_load_config_ignores_blank_lines_and_comments_and_strips_values(tmp_path: Path) -> None:
    """Allow readable spacing and comments while preserving the setting values."""
    images = tmp_path / "images"
    images.mkdir()
    config_path = tmp_path / "config.txt"
    config_path.write_text(
        f"  # pipeline settings\n\n image_dir = {images} \n n_workers = 3 \n",
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.image_dir == images.resolve()
    assert config.n_workers == 3


def test_load_config_resolves_relative_image_dir_from_config_location(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Resolve a relative image path beside the config, not the current directory."""
    project = tmp_path / "project"
    images = project / "dataset" / "images"
    images.mkdir(parents=True)
    config_path = write_config(project / "config.txt", "dataset/images")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    config = load_config(config_path)

    assert config.image_dir == images.resolve()


def test_load_config_accepts_utf8_bom(tmp_path: Path) -> None:
    """Read config files saved with the UTF-8 byte-order mark used by some editors."""
    images = tmp_path / "images"
    images.mkdir()
    config_path = tmp_path / "config.txt"
    config_path.write_text(f"image_dir={images}\nn_workers=1\n", encoding="utf-8-sig")

    assert load_config(config_path).n_workers == 1


@pytest.mark.parametrize(
    ("contents", "message"),
    [
        ("image_dir=images\nn_workers=1\nunknown=value\n", "Unknown config key"),
        ("image_dir=images\nimage_dir=other\nn_workers=1\n", "Duplicate config key"),
        ("image_dir=images\n", "Missing required config setting"),
        ("image_dir=images\nn_workers=1\nn_workers=2\n", "Duplicate config key"),
        ("image_dir=images\nn_workers\n", "expected key=value"),
        ("image_dir=\nn_workers=1\n", "key and value are required"),
    ],
)
def test_load_config_rejects_invalid_settings(tmp_path: Path, contents: str, message: str) -> None:
    """Reject malformed lines and unknown, repeated, empty, or missing settings."""
    config_path = tmp_path / "config.txt"
    config_path.write_text(contents, encoding="utf-8")

    with pytest.raises(ConfigError, match=message):
        load_config(config_path)


@pytest.mark.parametrize("worker_count", ["0", "-1", "one", "1.5", "1_0"])
def test_load_config_rejects_invalid_worker_counts(tmp_path: Path, worker_count: str) -> None:
    """Require the worker count to be a positive whole number."""
    images = tmp_path / "images"
    images.mkdir()
    config_path = write_config(tmp_path / "config.txt", str(images), worker_count)

    with pytest.raises(ConfigError, match="n_workers must be a positive integer"):
        load_config(config_path)


def test_load_config_reports_missing_file(tmp_path: Path) -> None:
    """Turn a missing config file into an actionable configuration error."""
    with pytest.raises(ConfigError, match="Cannot read config file"):
        load_config(tmp_path / "missing.txt")


def test_load_config_rejects_missing_image_directory(tmp_path: Path) -> None:
    """Reject a configured image directory that does not exist."""
    config_path = write_config(tmp_path / "config.txt", "missing-images")

    with pytest.raises(ConfigError, match="Image directory does not exist"):
        load_config(config_path)


def test_load_config_rejects_image_path_that_is_a_file(tmp_path: Path) -> None:
    """Reject an existing path when it points to a file instead of a directory."""
    not_a_directory = tmp_path / "file.txt"
    not_a_directory.write_text("not an image directory", encoding="utf-8")
    config_path = write_config(tmp_path / "config.txt", str(not_a_directory))

    with pytest.raises(ConfigError, match="Image path is not a directory"):
        load_config(config_path)


def test_enumerate_images_filters_sorts_and_assigns_ids(tmp_path: Path) -> None:
    """Keep supported top-level images, sort them, and number them from one."""
    images = tmp_path / "images"
    images.mkdir()
    for name in (
        "zebra.PNG",
        "alpha.jpg",
        "Beta.jpeg",
        "scan.bmp",
        "frame.gif",
        "page.tif",
        "document.tiff",
        "picture.webp",
        "._hidden.png",
        ".hidden.png",
        "labels.txt",
    ):
        (images / name).touch()
    (images / "nested").mkdir()
    (images / "nested" / "nested.png").touch()

    results = enumerate_images(images)

    assert results == (
        InputImage(image_id=1, path=images / "alpha.jpg"),
        InputImage(image_id=2, path=images / "Beta.jpeg"),
        InputImage(image_id=3, path=images / "document.tiff"),
        InputImage(image_id=4, path=images / "frame.gif"),
        InputImage(image_id=5, path=images / "page.tif"),
        InputImage(image_id=6, path=images / "picture.webp"),
        InputImage(image_id=7, path=images / "scan.bmp"),
        InputImage(image_id=8, path=images / "zebra.PNG"),
    )


def test_enumerate_images_rejects_empty_directory(tmp_path: Path) -> None:
    """Report an error when the directory contains no supported images."""
    images = tmp_path / "images"
    images.mkdir()

    with pytest.raises(ConfigError, match="No supported images found"):
        enumerate_images(images)


def test_enumerate_images_rejects_missing_directory(tmp_path: Path) -> None:
    """Reject image enumeration when the requested directory is absent."""
    with pytest.raises(ConfigError, match="Image directory does not exist"):
        enumerate_images(tmp_path / "missing")


def test_enumerate_images_rejects_file_path(tmp_path: Path) -> None:
    """Reject image enumeration when the supplied path is a file."""
    file_path = tmp_path / "file.txt"
    file_path.touch()

    with pytest.raises(ConfigError, match="Image path is not a directory"):
        enumerate_images(file_path)
