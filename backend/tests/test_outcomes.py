from __future__ import annotations

from aiobs.evaluation.outcomes import error, fail_min, pass_, skip


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
