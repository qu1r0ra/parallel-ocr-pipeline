from __future__ import annotations

import pytest

from parallel_ocr_pipeline.evaluation import character_accuracy, edit_distance, normalize, score


def test_normalization_ignores_case_spacing_and_punctuation() -> None:
    assert normalize(" Grape-Fruit!\n") == "grapefruit"


@pytest.mark.parametrize(
    ("expected", "actual", "distance"),
    [("grape", "grape", 0), ("grape", "grap", 1), ("grape", "gripe", 1), ("", "ab", 2)],
)
def test_edit_distance(expected: str, actual: str, distance: int) -> None:
    assert edit_distance(expected, actual) == distance


def test_failures_scored_as_empty_text_count_against_accuracy() -> None:
    scores = [score("grape", "grape"), score("lemon", "")]
    assert character_accuracy(scores) == pytest.approx(0.5)


def test_accuracy_requires_ground_truth() -> None:
    with pytest.raises(ValueError, match="ground-truth"):
        character_accuracy([])
