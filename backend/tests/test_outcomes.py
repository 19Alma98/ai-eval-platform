from __future__ import annotations

import pytest

from aiobs.evaluation.outcomes import error, fail_min, item_verdict, pass_, skip


def test_skip() -> None:
    result = skip("missing gold")
    assert result.label == "SKIPPED"
    assert result.score is None
    assert result.explanation == "missing gold"


def test_fail_min_default_score() -> None:
    result = fail_min("no documents retrieved")
    assert result.label == "FAIL"
    assert result.score == 0.0
    assert result.explanation == "no documents retrieved"


def test_error_includes_type() -> None:
    result = error("boom", error_type="TimeoutError")
    assert result.label == "ERROR"
    assert result.score is None
    assert result.metadata["error_type"] == "TimeoutError"


def test_pass_() -> None:
    result = pass_("ok", score=1.0, metadata={"k": 5})
    assert result.label == "PASS"
    assert result.score == 1.0
    assert result.metadata["k"] == 5


@pytest.mark.parametrize(
    ("score", "label", "threshold", "expected"),
    [
        # Both must pass: judge FAIL wins even above threshold.
        (0.9, "FAIL", 0.7, "FAIL"),
        # ...and score below threshold wins over judge PASS.
        (0.6, "PASS", 0.7, "FAIL"),
        (0.7, "PASS", 0.7, "PASS"),
        (0.6, "fail", None, "FAIL"),
        (0.6, "PASS", None, "PASS"),
        # No label: score decides.
        (0.8, None, 0.7, "PASS"),
        (0.5, None, 0.7, "FAIL"),
        (0.0, None, None, "FAIL"),
        (0.4, None, None, "PASS"),
        # Non-verdict outcomes pass through untouched.
        (None, "SKIPPED", 0.7, "SKIPPED"),
        (None, "ERROR", 0.7, "ERROR"),
        (None, None, 0.7, None),
        # FAIL label with no score still fails.
        (None, "FAIL", 0.7, "FAIL"),
    ],
)
def test_item_verdict(
    score: float | None, label: str | None, threshold: float | None, expected: str | None
) -> None:
    assert item_verdict(score, label, threshold) == expected
