from __future__ import annotations

from typing import Any

from aiobs.evaluation.protocol import EvaluationResult


def skip(explanation: str, *, metadata: dict[str, Any] | None = None) -> EvaluationResult:
    return EvaluationResult(
        score=None,
        label="SKIPPED",
        explanation=explanation,
        metadata=dict(metadata or {}),
    )


def fail_min(
    explanation: str,
    *,
    score: float = 0.0,
    metadata: dict[str, Any] | None = None,
) -> EvaluationResult:
    return EvaluationResult(
        score=score,
        label="FAIL",
        explanation=explanation,
        metadata=dict(metadata or {}),
    )


def error(
    explanation: str,
    *,
    error_type: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> EvaluationResult:
    meta = dict(metadata or {})
    if error_type is not None:
        meta.setdefault("error_type", error_type)
    return EvaluationResult(
        score=None,
        label="ERROR",
        explanation=explanation,
        metadata=meta,
    )


def pass_(
    explanation: str,
    *,
    score: float = 1.0,
    metadata: dict[str, Any] | None = None,
) -> EvaluationResult:
    return EvaluationResult(
        score=score,
        label="PASS",
        explanation=explanation,
        metadata=dict(metadata or {}),
    )


def item_verdict(score: float | None, label: str | None, threshold: float | None) -> str | None:
    """Single PASS/FAIL rule shared by offline runs and live scoring.

    Both signals must pass: a FAIL label fails even above the threshold, and a score
    below the threshold fails even with a PASS label. ERROR/SKIPPED pass through.
    Returns None when there is neither a label nor a score to judge.
    """
    normalized = (label or "").strip().upper() or None
    if normalized in {"ERROR", "SKIPPED"}:
        return normalized
    if normalized == "FAIL":
        return "FAIL"
    if threshold is not None and score is not None and score < threshold:
        return "FAIL"
    if normalized == "PASS":
        return "PASS"
    if score is None:
        return None
    if threshold is not None:
        return "PASS"
    return "FAIL" if score == 0.0 else "PASS"
