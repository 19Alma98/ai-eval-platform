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
