"""Shared filename contract for the supplied image dataset."""

EXPECTED_IMAGE_NAMES = frozenset(f"img{number:04}.png" for number in range(1, 101))
