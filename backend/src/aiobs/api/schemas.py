from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CreateProjectRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str | None = Field(default=None, min_length=1, max_length=200)


class ProjectResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    created_at: datetime

    model_config = {"from_attributes": True}


class HealthResponse(BaseModel):
    status: str


class SpanCreate(BaseModel):
    span_id: str = Field(min_length=1, max_length=16)
    parent_span_id: str | None = Field(default=None, max_length=16)
    name: str = Field(min_length=1, max_length=512)
    kind: str = Field(default="SPAN", max_length=64)
    start_time: datetime
    end_time: datetime | None = None
    status: str = Field(default="unset", max_length=32)
    attributes: dict[str, Any] = Field(default_factory=dict)
    events: list[dict[str, Any]] = Field(default_factory=list)


class CreateTraceRequest(BaseModel):
    trace_id: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=512)
    status: str = Field(default="unset", max_length=32)
    start_time: datetime
    end_time: datetime | None = None
    input: Any | None = None
    output: Any | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    environment: str | None = None
    user_id: str | None = None
    session_id: str | None = None
    spans: list[SpanCreate] = Field(default_factory=list)


class SpanResponse(BaseModel):
    span_id: str
    parent_span_id: str | None
    name: str
    kind: str
    start_time: datetime
    end_time: datetime | None
    status: str
    attributes: dict[str, Any]
    events: list[dict[str, Any]]


class TraceSummaryResponse(BaseModel):
    trace_id: str
    name: str
    status: str
    start_time: datetime
    end_time: datetime | None
    span_count: int


class TraceListResponse(BaseModel):
    items: list[TraceSummaryResponse]
    next_cursor: str | None = None


class TraceDetailResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    trace_id: str
    name: str
    status: str
    start_time: datetime
    end_time: datetime | None
    input: Any | None = None
    output: Any | None = None
    metadata: dict[str, Any]
    environment: str | None = None
    user_id: str | None = None
    session_id: str | None = None
    spans: list[SpanResponse]


class CreateDatasetRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    version: int = Field(default=1, ge=1)
    description: str | None = Field(default=None, max_length=2000)


class DatasetResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    version: int
    description: str | None
    created_at: datetime


class DatasetItemResponse(BaseModel):
    id: uuid.UUID
    dataset_id: uuid.UUID
    input: Any
    expected_output: Any | None = None
    actual_output: Any | None = None
    context: Any | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    source_trace_id: str | None = None
    source_span_id: str | None = None


class DatasetDetailResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    version: int
    description: str | None
    created_at: datetime
    items: list[DatasetItemResponse]


class CreateDatasetItemRequest(BaseModel):
    input: Any
    expected_output: Any | None = None
    actual_output: Any | None = None
    context: Any | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    source_trace_id: str | None = None
    source_span_id: str | None = None


class CreateDatasetItemFromTraceRequest(BaseModel):
    trace_id: str = Field(min_length=1, max_length=32)
    expected_output: Any | None = None
    source_span_id: str | None = Field(default=None, max_length=16)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CreateEvaluatorRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    type: str = Field(min_length=1, max_length=32)
    config: dict[str, Any]
    version: int = Field(default=1, ge=1)


class EvaluatorResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    type: str
    config: dict[str, Any]
    version: int


class CreateExperimentRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(min_length=1, max_length=200)
    dataset_id: uuid.UUID
    experiment_model_config: dict[str, Any] = Field(default_factory=dict, alias="model_config")
    application_version: str | None = Field(default=None, max_length=200)
    baseline_experiment_id: uuid.UUID | None = None


class ExperimentResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    dataset_id: uuid.UUID
    experiment_model_config: dict[str, Any] = Field(alias="model_config")
    application_version: str | None
    baseline_experiment_id: uuid.UUID | None
    status: str
    created_at: datetime


class EvaluateRequest(BaseModel):
    evaluator_ids: list[uuid.UUID] = Field(min_length=1)


class EvaluationResultResponse(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID
    dataset_item_id: uuid.UUID
    score: float | None
    label: str | None
    explanation: str | None
    metadata: dict[str, Any]
    duration_ms: int | None


class EvaluationRunResponse(BaseModel):
    id: uuid.UUID
    experiment_id: uuid.UUID
    evaluator_id: uuid.UUID
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    metadata: dict[str, Any]
    results: list[EvaluationResultResponse] = Field(default_factory=list)


class EvaluateResponse(BaseModel):
    experiment: ExperimentResponse
    runs: list[EvaluationRunResponse]
