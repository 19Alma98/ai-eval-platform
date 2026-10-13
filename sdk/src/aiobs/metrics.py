"""User-defined metrics scored in the user's process (experiments and production)."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

LABELS = frozenset({"PASS", "FAIL", "ERROR", "SKIPPED"})


@dataclass(frozen=True)
class Sample:
    """What a metric sees: one experiment item or one production call.

    In an experiment ``expected`` comes from the dataset item; in production it is
    ``None``. ``documents`` are the retrieved documents (``set_retrieval_documents``).
    """

    input: Any = None
    output: Any = None
    expected: Any = None
    documents: list[dict[str, Any]] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    trace_id: str | None = None
    item_id: str | None = None


@dataclass(frozen=True)
class Score:
    """A metric result. ``label`` overrides the threshold rule only to fail/skip/error."""

    value: float | None = None
    label: str | None = None
    explanation: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def _finite(value: Any) -> float | None:
    if value is None:
        return None
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"metric score must be finite, got {number}")
    return number


def _label(value: Any) -> str | None:
    if value is None or not str(value).strip():
        return None
    label = str(value).strip().upper()
    if label not in LABELS:
        raise ValueError(f"metric label must be one of {sorted(LABELS)}, got {value!r}")
    return label


def _explanation(value: Any) -> str | None:
    return None if value is None else str(value)


def coerce_score(value: Any) -> Score:
    """Normalize what a metric returned into a ``Score``; raises on anything unusable."""
    if isinstance(value, Score):
        return Score(
            _finite(value.value),
            _label(value.label),
            _explanation(value.explanation),
            dict(value.metadata),
        )
    if value is None:
        return Score()
    if isinstance(value, bool):
        return Score(1.0 if value else 0.0)
    if isinstance(value, int | float):
        return Score(_finite(value))
    if isinstance(value, Mapping) and "score" in value:
        inner = coerce_score(value["score"])
        return Score(
            inner.value,
            _label(value.get("label")),
            _explanation(value.get("explanation")),
            dict(value.get("metadata") or {}),
        )
    raise TypeError(
        f"metric must return Score, float, bool, None or {{'score': ...}}, got {value!r}"
    )
