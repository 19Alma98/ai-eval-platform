from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

UNSET: Any = object()


@dataclass(frozen=True, slots=True)
class ExperimentItemOutput:
    id: uuid.UUID
    experiment_id: uuid.UUID
    dataset_item_id: uuid.UUID
    actual_output: Any | None
    context: Any | None
    metadata: dict[str, Any]
    updated_at: datetime

    @classmethod
    def create(
        cls,
        experiment_id: uuid.UUID,
        dataset_item_id: uuid.UUID,
        *,
        actual_output: Any | None = None,
        context: Any | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ExperimentItemOutput:
        return cls(
            id=uuid.uuid4(),
            experiment_id=experiment_id,
            dataset_item_id=dataset_item_id,
            actual_output=actual_output,
            context=context,
            metadata=dict(metadata or {}),
            updated_at=datetime.now(UTC),
        )

    def with_patch(
        self,
        *,
        actual_output: Any = UNSET,
        context: Any = UNSET,
        metadata: Any = UNSET,
    ) -> ExperimentItemOutput:
        return ExperimentItemOutput(
            id=self.id,
            experiment_id=self.experiment_id,
            dataset_item_id=self.dataset_item_id,
            actual_output=self.actual_output if actual_output is UNSET else actual_output,
            context=self.context if context is UNSET else context,
            metadata=dict(self.metadata) if metadata is UNSET else dict(metadata or {}),
            updated_at=datetime.now(UTC),
        )
