"""Production conversations: session-grouped turns and session-level scores."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

JUDGE_STATUSES = frozenset({"pending", "running", "scored", "error", "unsampled", "open"})


@dataclass(frozen=True, slots=True)
class ConversationScore:
    id: uuid.UUID
    conversation_id: uuid.UUID
    evaluator_id: uuid.UUID | None
    kind: str
    score: float | None
    label: str | None
    explanation: str | None
    threshold: float | None
    metadata: dict[str, Any]
    created_at: datetime

    @classmethod
    def create(
        cls,
        conversation_id: uuid.UUID,
        *,
        kind: str,
        evaluator_id: uuid.UUID | None = None,
        score: float | None = None,
        label: str | None = None,
        explanation: str | None = None,
        threshold: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ConversationScore:
        return cls(
            id=uuid.uuid4(),
            conversation_id=conversation_id,
            evaluator_id=evaluator_id,
            kind=kind,
            score=score,
            label=label,
            explanation=explanation,
            threshold=threshold,
            metadata=dict(metadata or {}),
            created_at=datetime.now(UTC),
        )


@dataclass(frozen=True, slots=True)
class Conversation:
    id: uuid.UUID
    project_id: uuid.UUID
    session_id: str
    user_id: str | None
    environment: str | None
    turn_count: int
    started_at: datetime
    last_activity_at: datetime
    judge_status: str
    metrics_set_id: uuid.UUID | None
    score_warning: str | None
    error_message: str | None
    created_at: datetime
    scored_at: datetime | None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        project_id: uuid.UUID,
        session_id: str,
        *,
        user_id: str | None = None,
        environment: str | None = None,
        turn_count: int = 0,
        started_at: datetime | None = None,
        last_activity_at: datetime | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Conversation:
        now = datetime.now(UTC)
        return cls(
            id=uuid.uuid4(),
            project_id=project_id,
            session_id=session_id.strip(),
            user_id=user_id,
            environment=environment,
            turn_count=turn_count,
            started_at=started_at or now,
            last_activity_at=last_activity_at or now,
            judge_status="open",
            metrics_set_id=None,
            score_warning=None,
            error_message=None,
            created_at=now,
            scored_at=None,
            metadata=dict(metadata or {}),
        )

    def with_activity(
        self,
        *,
        turn_count: int,
        last_activity_at: datetime,
        user_id: str | None = None,
        environment: str | None = None,
    ) -> Conversation:
        return replace(
            self,
            turn_count=turn_count,
            last_activity_at=last_activity_at,
            user_id=user_id if user_id is not None else self.user_id,
            environment=environment if environment is not None else self.environment,
        )

    def with_status(
        self,
        judge_status: str,
        *,
        metrics_set_id: uuid.UUID | None = None,
        score_warning: str | None = None,
        error_message: str | None = None,
        scored_at: datetime | None = None,
    ) -> Conversation:
        if judge_status not in JUDGE_STATUSES:
            raise ValueError(f"Invalid judge_status: {judge_status}")
        return replace(
            self,
            judge_status=judge_status,
            metrics_set_id=metrics_set_id if metrics_set_id is not None else self.metrics_set_id,
            score_warning=score_warning,
            error_message=error_message,
            scored_at=scored_at if scored_at is not None else self.scored_at,
        )


@dataclass(frozen=True, slots=True)
class ConversationSummary:
    """Aggregated session row for list views (may not yet be persisted)."""

    session_id: str
    user_id: str | None
    environment: str | None
    turn_count: int
    started_at: datetime
    last_activity_at: datetime
    conversation_id: uuid.UUID | None = None
    judge_status: str | None = None
    failing_score_kinds: tuple[str, ...] = ()
