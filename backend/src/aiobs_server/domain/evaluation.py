from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

RUN_STATUSES = frozenset({"PENDING", "RUNNING", "PASSED", "FAILED", "ERROR", "SKIPPED"})


@dataclass(frozen=True, slots=True)
class EvaluationRun:
    id: uuid.UUID
    experiment_id: uuid.UUID
    evaluator_id: uuid.UUID
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        experiment_id: uuid.UUID,
        evaluator_id: uuid.UUID,
        *,
        status: str = "PENDING",
        metadata: dict[str, Any] | None = None,
    ) -> EvaluationRun:
        if status not in RUN_STATUSES:
            raise ValueError(f"Invalid evaluation run status: {status}")
        return cls(
            id=uuid.uuid4(),
            experiment_id=experiment_id,
            evaluator_id=evaluator_id,
            status=status,
            started_at=None,
            finished_at=None,
            metadata=dict(metadata or {}),
        )

    def with_status(
        self,
        status: str,
        *,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> EvaluationRun:
        if status not in RUN_STATUSES:
            raise ValueError(f"Invalid evaluation run status: {status}")
        return EvaluationRun(
            id=self.id,
            experiment_id=self.experiment_id,
            evaluator_id=self.evaluator_id,
            status=status,
            started_at=started_at if started_at is not None else self.started_at,
            finished_at=finished_at if finished_at is not None else self.finished_at,
            metadata=dict(metadata) if metadata is not None else dict(self.metadata),
        )


@dataclass(frozen=True, slots=True)
class EvaluationResultRecord:
    id: uuid.UUID
    run_id: uuid.UUID
    dataset_item_id: uuid.UUID
    score: float | None
    label: str | None
    explanation: str | None
    metadata: dict[str, Any]
    duration_ms: int | None

    @classmethod
    def create(
        cls,
        run_id: uuid.UUID,
        dataset_item_id: uuid.UUID,
        *,
        score: float | None = None,
        label: str | None = None,
        explanation: str | None = None,
        metadata: dict[str, Any] | None = None,
        duration_ms: int | None = None,
    ) -> EvaluationResultRecord:
        return cls(
            id=uuid.uuid4(),
            run_id=run_id,
            dataset_item_id=dataset_item_id,
            score=score,
            label=label,
            explanation=explanation,
            metadata=dict(metadata or {}),
            duration_ms=duration_ms,
        )


def utc_now() -> datetime:
    return datetime.now(UTC)
