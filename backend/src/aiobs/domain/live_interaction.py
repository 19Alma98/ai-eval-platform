from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

JUDGE_STATUSES = frozenset({"pending", "running", "scored", "error"})
REVIEW_VERDICTS = frozenset({"agree", "disagree"})

# Metrics kinds safe to run without expected_output / gold labels.
GOLDLESS_METRIC_KINDS = frozenset({"groundedness", "answer_relevance"})


class DuplicateExternalIdError(Exception):
    """Another interaction with the same (project_id, external_id) already exists."""

    def __init__(self, external_id: str) -> None:
        self.external_id = external_id
        super().__init__(f"Live interaction external_id already exists: {external_id}")


@dataclass(frozen=True, slots=True)
class LiveInteraction:
    id: uuid.UUID
    project_id: uuid.UUID
    question: str
    answer: str
    documents: list[dict[str, Any]]
    metadata: dict[str, Any]
    external_id: str | None
    judge_status: str
    metrics_set_id: uuid.UUID | None
    score_warning: str | None
    error_message: str | None
    created_at: datetime
    scored_at: datetime | None

    @classmethod
    def create(
        cls,
        project_id: uuid.UUID,
        question: str,
        answer: str,
        *,
        documents: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
        external_id: str | None = None,
        metrics_set_id: uuid.UUID | None = None,
    ) -> LiveInteraction:
        q = question.strip()
        a = answer.strip()
        if not q:
            raise ValueError("question must not be empty")
        if not a:
            raise ValueError("answer must not be empty")
        ext = external_id.strip() if external_id else None
        if external_id is not None and not ext:
            raise ValueError("external_id must not be empty when provided")
        status = "pending"
        if status not in JUDGE_STATUSES:
            raise ValueError(f"invalid judge_status: {status}")
        return cls(
            id=uuid.uuid4(),
            project_id=project_id,
            question=q,
            answer=a,
            documents=list(documents or []),
            metadata=dict(metadata or {}),
            external_id=ext,
            judge_status=status,
            metrics_set_id=metrics_set_id,
            score_warning=None,
            error_message=None,
            created_at=datetime.now(UTC),
            scored_at=None,
        )

    def with_status(
        self,
        judge_status: str,
        *,
        score_warning: str | None | object = ...,
        error_message: str | None | object = ...,
        metrics_set_id: uuid.UUID | None | object = ...,
        scored_at: datetime | None | object = ...,
    ) -> LiveInteraction:
        if judge_status not in JUDGE_STATUSES:
            raise ValueError(f"invalid judge_status: {judge_status}")
        kwargs: dict[str, Any] = {"judge_status": judge_status}
        if score_warning is not ...:
            kwargs["score_warning"] = score_warning
        if error_message is not ...:
            kwargs["error_message"] = error_message
        if metrics_set_id is not ...:
            kwargs["metrics_set_id"] = metrics_set_id
        if scored_at is not ...:
            kwargs["scored_at"] = scored_at
        return replace(self, **kwargs)


@dataclass(frozen=True, slots=True)
class LiveInteractionScore:
    id: uuid.UUID
    live_interaction_id: uuid.UUID
    evaluator_id: uuid.UUID | None
    kind: str
    score: float | None
    label: str | None
    explanation: str | None
    threshold: float | None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        live_interaction_id: uuid.UUID,
        kind: str,
        *,
        evaluator_id: uuid.UUID | None = None,
        score: float | None = None,
        label: str | None = None,
        explanation: str | None = None,
        threshold: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> LiveInteractionScore:
        cleaned = kind.strip()
        if not cleaned:
            raise ValueError("kind must not be empty")
        return cls(
            id=uuid.uuid4(),
            live_interaction_id=live_interaction_id,
            evaluator_id=evaluator_id,
            kind=cleaned,
            score=score,
            label=label,
            explanation=explanation,
            threshold=threshold,
            created_at=datetime.now(UTC),
            metadata=dict(metadata or {}),
        )


@dataclass(frozen=True, slots=True)
class LiveReview:
    id: uuid.UUID
    live_interaction_id: uuid.UUID
    verdict: str
    note: str | None
    reviewer: str | None
    created_at: datetime

    @classmethod
    def create(
        cls,
        live_interaction_id: uuid.UUID,
        verdict: str,
        *,
        note: str | None = None,
        reviewer: str | None = None,
    ) -> LiveReview:
        v = verdict.strip().lower()
        if v not in REVIEW_VERDICTS:
            raise ValueError(f"verdict must be one of: {', '.join(sorted(REVIEW_VERDICTS))}")
        cleaned_note = note.strip() if note else None
        return cls(
            id=uuid.uuid4(),
            live_interaction_id=live_interaction_id,
            verdict=v,
            note=cleaned_note or None,
            reviewer=reviewer.strip() if reviewer else None,
            created_at=datetime.now(UTC),
        )


@dataclass(frozen=True, slots=True)
class LiveScoreReview:
    """Per-score human review: agree/disagree with judge label + optional explanation edit."""

    id: uuid.UUID
    live_interaction_score_id: uuid.UUID
    verdict: str
    corrected_explanation: str | None
    note: str | None
    reviewer: str | None
    created_at: datetime

    @classmethod
    def create(
        cls,
        live_interaction_score_id: uuid.UUID,
        verdict: str,
        *,
        corrected_explanation: str | None = None,
        note: str | None = None,
        reviewer: str | None = None,
    ) -> LiveScoreReview:
        v = verdict.strip().lower()
        if v not in REVIEW_VERDICTS:
            raise ValueError(f"verdict must be one of: {', '.join(sorted(REVIEW_VERDICTS))}")
        cleaned_explanation = (
            corrected_explanation.strip() if corrected_explanation else None
        )
        cleaned_note = note.strip() if note else None
        return cls(
            id=uuid.uuid4(),
            live_interaction_score_id=live_interaction_score_id,
            verdict=v,
            corrected_explanation=cleaned_explanation or None,
            note=cleaned_note or None,
            reviewer=reviewer.strip() if reviewer else None,
            created_at=datetime.now(UTC),
        )


def filter_goldless_entries(entries: list[Any]) -> list[Any]:
    """Keep enabled metrics-set entries whose kind is in GOLDLESS_METRIC_KINDS."""
    out = []
    for entry in entries:
        kind = str(getattr(entry, "kind", "")).strip()
        enabled = bool(getattr(entry, "enabled", False))
        if enabled and kind in GOLDLESS_METRIC_KINDS:
            out.append(entry)
    return out
