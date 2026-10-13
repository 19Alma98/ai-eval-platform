from __future__ import annotations

import math
from fractions import Fraction

import pytest

from aiobs.metrics import Sample, Score, coerce_score


def test_sample_defaults_are_empty() -> None:
    sample = Sample(input="q", output="a")
    assert sample.expected is None
    assert sample.documents == [] and sample.context == {} and sample.metadata == {}
    assert sample.trace_id is None and sample.item_id is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, Score()),
        (True, Score(1.0)),
        (False, Score(0.0)),
        (1, Score(1.0)),
        (0.25, Score(0.25)),
        ({"score": 0.5}, Score(0.5)),
        (
            {"score": True, "label": "pass", "explanation": "ok", "metadata": {"k": 1}},
            Score(1.0, label="PASS", explanation="ok", metadata={"k": 1}),
        ),
        (Score(0.3, label="fail"), Score(0.3, label="FAIL")),
        (
            {"score": Score(0.3, label="FAIL", explanation="x", metadata={"k": 1})},
            Score(0.3, label="FAIL", explanation="x", metadata={"k": 1}),
        ),
        (Fraction(1, 4), Score(0.25)),
    ],
)
def test_coerce_score_accepts_supported_returns(raw: object, expected: Score) -> None:
    assert coerce_score(raw) == expected


@pytest.mark.parametrize("raw", ["0.5", [0.5], {"value": 0.5}, object()])
def test_coerce_score_rejects_other_types(raw: object) -> None:
    with pytest.raises(TypeError, match="metric must return"):
        coerce_score(raw)


@pytest.mark.parametrize("raw", [math.nan, math.inf, {"score": -math.inf}, Score(math.nan)])
def test_coerce_score_rejects_non_finite(raw: object) -> None:
    with pytest.raises(ValueError, match="finite"):
        coerce_score(raw)


def test_coerce_score_rejects_unknown_label() -> None:
    with pytest.raises(ValueError, match="label"):
        coerce_score(Score(1.0, label="MAYBE"))
