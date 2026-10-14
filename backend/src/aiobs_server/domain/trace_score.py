"""Scores attached to an OTel trace: SDK metrics, end-user feedback, external judges.

Keyed by trace id without a foreign key, so a score may arrive before its trace is
ingested. One row per (project, trace, name, source, author); writes upsert.
"""

from __future__ import annotations

import math
import re
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

TRACE_ID_PATTERN = re.compile(r"[0-9a-f]{32}")
TRACE_SCORE_SOURCES = frozenset({"sdk", "human", "judge"})
TRACE_SCORE_LABELS = frozenset({"PASS", "FAIL", "ERROR", "SKIPPED"})
MAX_TRACE_SCORE_BATCH = 500
MAX_NAME_LENGTH = 200
MAX_TRACE_SCORE_METADATA_BYTES = 16_384


def normalize_trace_id(value: str) -> str:
    cleaned = value.strip().lower()
    if not TRACE_ID_PATTERN.fullmatch(cleaned):
        raise ValueError(f"trace_id must be 32 hex characters, got {value!r}")
    return cleaned


def _finite(field_name: str, value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{field_name} must be a number, got {value!r}")
    try:
        number = float(value)
    except OverflowError:
        raise ValueError(f"{field_name} must be finite") from None
    if not math.isfinite(number):
        raise ValueError(f"{field_name} must be finite")
    return number


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


@dataclass(frozen=True, slots=True)
class TraceScore:
    id: uuid.UUID
    project_id: uuid.UUID
    trace_id: str
    name: str
    value: float | None
    label: str | None
    explanation: str | None
    threshold: float | None
    source: str
    author: str | None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def key(self) -> tuple[uuid.UUID, str, str, str, str]:
        """Upsert key; a missing author is stored as ``''``."""
        return (self.project_id, self.trace_id, self.name, self.source, self.author or "")

    @classmethod
    def create(
        cls,
        project_id: uuid.UUID,
        trace_id: str,
        name: str,
        *,
        value: Any = None,
        label: str | None = None,
        explanation: str | None = None,
        threshold: Any = None,
        source: str = "sdk",
        author: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> TraceScore:
        cleaned_name = name.strip()
        if not cleaned_name or len(cleaned_name) > MAX_NAME_LENGTH:
            raise ValueError(f"name must be 1-{MAX_NAME_LENGTH} characters")
        if source not in TRACE_SCORE_SOURCES:
            raise ValueError(f"source must be one of {sorted(TRACE_SCORE_SOURCES)}, got {source!r}")
        cleaned_label = _blank_to_none(label)
        if cleaned_label is not None:
            cleaned_label = cleaned_label.upper()
            if cleaned_label not in TRACE_SCORE_LABELS:
                raise ValueError(
                    f"label must be one of {sorted(TRACE_SCORE_LABELS)}, got {label!r}"
                )
        now = datetime.now(UTC)
        return cls(
            id=uuid.uuid4(),
            project_id=project_id,
            trace_id=normalize_trace_id(trace_id),
            name=cleaned_name,
            value=_finite("value", value),
            label=cleaned_label,
            explanation=explanation,
            threshold=_finite("threshold", threshold),
            source=source,
            author=_blank_to_none(author),
            metadata=dict(metadata or {}),
            created_at=now,
            updated_at=now,
        )

    def with_label(self, label: str | None) -> TraceScore:
        return replace(self, label=label)


@dataclass(frozen=True, slots=True)
class TraceScoreSummaryRow:
    name: str
    source: str
    count: int
    mean: float | None
    pass_rate: float | None


def trace_score_is_failed(score: TraceScore) -> bool:
    """FAIL counts (an SDK metric under its threshold, or a thumbs-down)."""
    return score.label == "FAIL"


def summarize_trace_scores(scores: Iterable[TraceScore]) -> list[TraceScoreSummaryRow]:
    """Per (name, source): count, mean value, pass rate over PASS/FAIL labels only.

    Reference implementation used by the in-memory repository.
    """
    groups: dict[tuple[str, str], list[TraceScore]] = {}
    for score in scores:
        groups.setdefault((score.name, score.source), []).append(score)
    rows: list[TraceScoreSummaryRow] = []
    for (name, source), items in sorted(groups.items()):
        values = [s.value for s in items if s.value is not None]
        judged = [s for s in items if s.label in {"PASS", "FAIL"}]
        n_pass = sum(1 for s in judged if s.label == "PASS")
        rows.append(
            TraceScoreSummaryRow(
                name=name,
                source=source,
                count=len(items),
                mean=sum(values) / len(values) if values else None,
                pass_rate=n_pass / len(judged) if judged else None,
            )
        )
    return rows
