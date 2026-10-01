from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

EXPERIMENT_STATUSES = frozenset({"created", "running", "completed", "failed", "cancelled"})


@dataclass(frozen=True, slots=True)
class Experiment:
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    dataset_id: uuid.UUID
    model_config: dict[str, Any]
    application_version: str | None
    baseline_experiment_id: uuid.UUID | None
    status: str
    created_at: datetime

    @classmethod
    def create(
        cls,
        project_id: uuid.UUID,
        name: str,
        dataset_id: uuid.UUID,
        *,
        model_config: dict[str, Any] | None = None,
        application_version: str | None = None,
        baseline_experiment_id: uuid.UUID | None = None,
        status: str = "created",
    ) -> Experiment:
        cleaned = name.strip()
        if not cleaned:
            raise ValueError("Experiment name must not be empty")
        if status not in EXPERIMENT_STATUSES:
            raise ValueError(f"Invalid experiment status: {status}")
        return cls(
            id=uuid.uuid4(),
            project_id=project_id,
            name=cleaned,
            dataset_id=dataset_id,
            model_config=dict(model_config or {}),
            application_version=application_version,
            baseline_experiment_id=baseline_experiment_id,
            status=status,
            created_at=datetime.now(UTC),
        )
