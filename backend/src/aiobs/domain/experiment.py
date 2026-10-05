from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
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
    version: str | None
    baseline_experiment_id: uuid.UUID | None
    status: str
    created_at: datetime
    app_config_id: uuid.UUID | None = None
    metrics_set_id: uuid.UUID | None = None

    @classmethod
    def create(
        cls,
        project_id: uuid.UUID,
        name: str,
        dataset_id: uuid.UUID,
        *,
        model_config: dict[str, Any] | None = None,
        version: str | None = None,
        baseline_experiment_id: uuid.UUID | None = None,
        app_config_id: uuid.UUID | None = None,
        metrics_set_id: uuid.UUID | None = None,
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
            version=version,
            baseline_experiment_id=baseline_experiment_id,
            status=status,
            created_at=datetime.now(UTC),
            app_config_id=app_config_id,
            metrics_set_id=metrics_set_id,
        )

    def with_metrics_set_id(self, metrics_set_id: uuid.UUID | None) -> Experiment:
        return replace(self, metrics_set_id=metrics_set_id)
