"""Character-level recognition-quality metric against filename-to-word ground truth."""

from __future__ import annotations

import csv
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

PASS_THRESHOLD = 0.5


def normalize(text: str) -> str:
    """Casefold and keep only letters and digits, ignoring spacing, punctuation, and case."""
    folded = unicodedata.normalize("NFKC", text).casefold()
    return "".join(character for character in folded if character.isalnum())


def edit_distance(expected: str, actual: str) -> int:
    """Levenshtein distance counting insertions, deletions, and substitutions."""
    previous = list(range(len(actual) + 1))
    for row, expected_character in enumerate(expected, start=1):
        current = [row]
        for column, actual_character in enumerate(actual, start=1):
            current.append(
                min(
                    previous[column] + 1,
                    current[column - 1] + 1,
                    previous[column - 1] + (expected_character != actual_character),
                )
            )
        previous = current
    return previous[-1]


@dataclass(frozen=True)
class Score:
    """Normalized comparison of one prediction with its label."""

    expected: str
    actual: str
    distance: int

    @property
    def accuracy(self) -> float:
        return max(0.0, 1 - self.distance / len(self.expected)) if self.expected else 1.0


def score(label: str, prediction: str) -> Score:
    expected = normalize(label)
    actual = normalize(prediction)
    return Score(expected, actual, edit_distance(expected, actual))


def character_accuracy(scores: Iterable[Score]) -> float:
    """Micro-averaged accuracy: one minus total edits over total expected characters.

    Image failures should be scored against an empty prediction, so every label contributes its
    full length to the denominator and an unrecognized image cannot hide a weak result.
    """
    collected = list(scores)
    total = sum(len(item.expected) for item in collected)
    if total == 0:
        raise ValueError("no ground-truth characters to evaluate")
    return max(0.0, 1 - sum(item.distance for item in collected) / total)


def read_labels(path: Path) -> Mapping[str, str]:
    """Read ``filename,word`` rows with a header into an ordered filename-to-word mapping."""
    with path.open(newline="", encoding="utf-8") as handle:
        return {row["filename"]: row["word"] for row in csv.DictReader(handle)}
