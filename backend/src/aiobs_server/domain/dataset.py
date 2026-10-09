from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from aiobs_server.domain.task_types import normalize_task_type


@dataclass(frozen=True, slots=True)
class Dataset:
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    version: int
    description: str | None
    task_type: str | None
    created_at: datetime

    @classmethod
    def create(
        cls,
        project_id: uuid.UUID,
        name: str,
        *,
        version: int = 1,
        description: str | None = None,
        task_type: str | None = None,
    ) -> Dataset:
        cleaned = name.strip()
        if not cleaned:
            raise ValueError("Dataset name must not be empty")
        if version < 1:
            raise ValueError("Dataset version must be >= 1")
        return cls(
            id=uuid.uuid4(),
            project_id=project_id,
            name=cleaned,
            version=version,
            description=description.strip() if description else None,
            task_type=normalize_task_type(task_type) or "rag_qa",
            created_at=datetime.now(UTC),
        )


@dataclass(frozen=True, slots=True)
class DatasetItem:
    id: uuid.UUID
    dataset_id: uuid.UUID
    input: Any
    expected_output: Any | None = None
    actual_output: Any | None = None
    context: Any | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    source_trace_id: str | None = None
    source_span_id: str | None = None

    @classmethod
    def create(
        cls,
        dataset_id: uuid.UUID,
        input: Any,
        *,
        expected_output: Any | None = None,
        actual_output: Any | None = None,
        context: Any | None = None,
        metadata: dict[str, Any] | None = None,
        source_trace_id: str | None = None,
        source_span_id: str | None = None,
    ) -> DatasetItem:
        return cls(
            id=uuid.uuid4(),
            dataset_id=dataset_id,
            input=input,
            expected_output=expected_output,
            actual_output=actual_output,
            context=context,
            metadata=dict(metadata or {}),
            source_trace_id=source_trace_id,
            source_span_id=source_span_id,
        )
