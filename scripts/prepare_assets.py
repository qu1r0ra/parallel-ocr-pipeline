"""Prepare the local OCR dataset without extracting archive metadata."""

from __future__ import annotations

import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from zipfile import ZipFile, ZipInfo

from asset_contract import EXPECTED_IMAGE_NAMES

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCAL_ASSETS = PROJECT_ROOT / "local-assets"
ARCHIVE = LOCAL_ASSETS / "supplied" / "dataset.zip"
DATASET = LOCAL_ASSETS / "dataset"
IMAGE_DIRECTORY = DATASET / "images"
LABELS_FILE = DATASET / "labels.txt"
IMAGE_NAME = re.compile(r"img\d{4}\.png\Z")


def _members(archive: ZipFile) -> tuple[list[ZipInfo], ZipInfo]:
    images: list[ZipInfo] = []
    labels: list[ZipInfo] = []

    for member in archive.infolist():
        normalized = member.filename.replace("\\", "/")
        parts = normalized.split("/")
        if "__MACOSX" in parts or member.is_dir():
            continue
        if len(parts) != 2 or parts[0] != "dataset":
            continue
        if parts[1] == "labels.txt":
            labels.append(member)
        elif IMAGE_NAME.fullmatch(parts[1]):
            images.append(member)

    image_names = [
        member.filename.replace("\\", "/").rsplit("/", maxsplit=1)[-1] for member in images
    ]
    if set(image_names) != EXPECTED_IMAGE_NAMES or len(image_names) != len(EXPECTED_IMAGE_NAMES):
        missing = sorted(EXPECTED_IMAGE_NAMES - set(image_names))
        extra = sorted(set(image_names) - EXPECTED_IMAGE_NAMES)
        raise ValueError(
            "Expected exactly img0001.png through img0100.png in dataset/. "
            f"Missing: {missing[:5]}; unexpected: {extra[:5]}."
        )
    if len(labels) != 1:
        raise ValueError("Expected one dataset/labels.txt file in the course archive.")
    return sorted(images, key=lambda item: item.filename), labels[0]


def _copy_member(archive: ZipFile, member: ZipInfo, destination: Path) -> None:
    with archive.open(member) as source, destination.open("wb") as target:
        shutil.copyfileobj(source, target)


def _existing_dataset_is_complete() -> bool:
    if not DATASET.exists():
        return False

    names = {path.name for path in IMAGE_DIRECTORY.iterdir()} if IMAGE_DIRECTORY.is_dir() else set()
    if names == EXPECTED_IMAGE_NAMES and LABELS_FILE.is_file():
        print(f"The 100 images and labels are already prepared under {DATASET}.")
        return True

    raise FileExistsError(
        f"{DATASET} already exists but is incomplete. Move it aside, then run "
        "`just prepare-assets` again; the task will not overwrite local files."
    )


def prepare() -> None:
    if not ARCHIVE.is_file():
        raise FileNotFoundError(
            f"Dataset archive not found: {ARCHIVE}\n"
            "Copy the supplied archive to local-assets/supplied/dataset.zip, "
            "then run `just prepare-assets`."
        )
    if _existing_dataset_is_complete():
        return

    with ZipFile(ARCHIVE) as archive:
        images, labels = _members(archive)
        with tempfile.TemporaryDirectory(prefix=".dataset-staging-", dir=LOCAL_ASSETS) as temp:
            staged_dataset = Path(temp) / "dataset"
            staged_images = staged_dataset / "images"
            staged_images.mkdir(parents=True)
            for member in images:
                name = member.filename.replace("\\", "/").rsplit("/", maxsplit=1)[-1]
                _copy_member(archive, member, staged_images / name)
            _copy_member(archive, labels, staged_dataset / "labels.txt")

            if {path.name for path in staged_images.iterdir()} != EXPECTED_IMAGE_NAMES:
                raise OSError("The extracted image set did not match the expected 100 files.")
            staged_dataset.rename(DATASET)

    print(f"Prepared 100 source images in {IMAGE_DIRECTORY}.")
    print(f"Kept ground-truth labels separately at {LABELS_FILE}.")
    print("Ignored __MACOSX entries and all other archive metadata.")


def main() -> int:
    try:
        prepare()
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        print(f"Asset preparation failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
