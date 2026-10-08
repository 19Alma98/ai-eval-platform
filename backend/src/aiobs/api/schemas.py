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
    task_type: str | None = Field(default="rag_qa", max_length=64)


class DatasetResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    version: int
    description: str | None
    task_type: str | None = None
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
    task_type: str | None = None
    created_at: datetime
    items: list[DatasetItemResponse]


class TaskTypeResponse(BaseModel):
    id: str
    label: str
    field_hints: list[str]
    recommended_evaluator_kinds: list[str]


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


class ImportDatasetItemErrorResponse(BaseModel):
    row: int
    message: str


class ImportDatasetItemsResponse(BaseModel):
    created: int
    errors: list[ImportDatasetItemErrorResponse]


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


class MetricsPackEntryRequest(BaseModel):
    kind: str = Field(min_length=1, max_length=64)
    enabled: bool
    threshold: float | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    evaluator_id: uuid.UUID | None = None
    removable: bool | None = None


class ReplaceMetricsPackRequest(BaseModel):
    entries: list[MetricsPackEntryRequest] = Field(min_length=1)


class MetricsPackEntryResponse(BaseModel):
    kind: str
    enabled: bool
    threshold: float | None
    config: dict[str, Any]
    evaluator_id: uuid.UUID | None
    removable: bool


class MetricsPackResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    entries: list[MetricsPackEntryResponse]
    updated_at: datetime


class MetricsSetEntryRequest(BaseModel):
    kind: str = Field(min_length=1, max_length=64)
    enabled: bool
    threshold: float | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    evaluator_id: uuid.UUID | None = None


class CreateMetricsSetRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    entries: list[MetricsSetEntryRequest] = Field(min_length=1)


class PatchMetricsSetRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    entries: list[MetricsSetEntryRequest] | None = None


class VersionMetricsSetRequest(BaseModel):
    description: str | None = Field(default=None, max_length=2000)
    entries: list[MetricsSetEntryRequest] | None = None


class MetricsSetEntryResponse(BaseModel):
    id: uuid.UUID
    kind: str
    enabled: bool
    threshold: float | None
    config: dict[str, Any]
    evaluator_id: uuid.UUID | None
    is_default: bool
    created_at: datetime


class MetricsSetSummaryResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    version: int
    description: str | None
    is_project_default: bool
    created_at: datetime
    updated_at: datetime
    entry_count: int
    enabled_count: int


class MetricsSetResponse(MetricsSetSummaryResponse):
    entries: list[MetricsSetEntryResponse]


class CreateExperimentRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(min_length=1, max_length=200)
    dataset_id: uuid.UUID
    experiment_model_config: dict[str, Any] = Field(default_factory=dict, alias="model_config")
    version: str | None = Field(default=None, max_length=200)
    baseline_experiment_id: uuid.UUID | None = None
    app_config_id: uuid.UUID | None = None
    app_config_alias: str | None = None
    metrics_set_id: uuid.UUID | None = None


class ExperimentResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    dataset_id: uuid.UUID
    experiment_model_config: dict[str, Any] = Field(alias="model_config")
    version: str | None
    baseline_experiment_id: uuid.UUID | None
    app_config_id: uuid.UUID | None = None
    metrics_set_id: uuid.UUID | None = None
    status: str
    created_at: datetime


class EvaluateRequest(BaseModel):
    evaluator_ids: list[uuid.UUID] = Field(min_length=1)


class EvaluatePackRequest(BaseModel):
    metrics_set_id: uuid.UUID | None = None
    save_as_default: bool = False


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


class EvaluatorSummaryResponse(BaseModel):
    evaluator_id: uuid.UUID
    evaluator_name: str | None = None
    run_id: uuid.UUID
    status: str
    n_items: int
    n_scored: int
    n_error: int
    n_skipped: int
    mean_score: float | None
    pass_rate: float | None


class ExperimentSummaryResponse(BaseModel):
    experiment_id: uuid.UUID
    evaluators: list[EvaluatorSummaryResponse]


class MetricComparisonResponse(BaseModel):
    evaluator_id: uuid.UUID
    evaluator_name: str | None = None
    metric: str
    candidate: float | None
    baseline: float | None
    delta: float | None
    status: str


class ExperimentCompareResponse(BaseModel):
    experiment_id: uuid.UUID
    baseline_experiment_id: uuid.UUID
    metrics: list[MetricComparisonResponse]
    regressions: list[MetricComparisonResponse]
    improved: list[MetricComparisonResponse]
    unchanged: list[MetricComparisonResponse]


class ReleaseCheckRequest(BaseModel):
    experiment_id: uuid.UUID
    policy: dict[str, Any]
    baseline_experiment_id: uuid.UUID | None = None


class ReleaseCheckItemResponse(BaseModel):
    metric: str
    actual: float | None
    threshold: float | None
    status: str


class ReleaseCheckResponse(BaseModel):
    status: str
    experiment_id: uuid.UUID
    baseline_experiment_id: uuid.UUID | None
    checks: list[ReleaseCheckItemResponse]


class UpsertExperimentOutputItemRequest(BaseModel):
    dataset_item_id: uuid.UUID
    actual_output: Any | None = None
    context: Any | None = None
    metadata: dict[str, Any] | None = None


class UpsertExperimentOutputsRequest(BaseModel):
    items: list[UpsertExperimentOutputItemRequest] = Field(min_length=1)


class ExperimentItemOutputResponse(BaseModel):
    id: uuid.UUID
    experiment_id: uuid.UUID
    dataset_item_id: uuid.UUID
    actual_output: Any | None
    context: Any | None
    metadata: dict[str, Any]
    updated_at: datetime


class UpsertExperimentOutputsResponse(BaseModel):
    upserted: int
    items: list[ExperimentItemOutputResponse]


class ItemSideResponse(BaseModel):
    actual_output: Any | None = None
    context: Any | None = None
    score: float | None = None
    label: str | None = None
    explanation: str | None = None
    run_id: uuid.UUID | None = None


class ItemComparisonRowResponse(BaseModel):
    dataset_item_id: uuid.UUID
    input: Any
    expected_output: Any | None = None
    baseline: ItemSideResponse
    candidate: ItemSideResponse
    delta: float | None = None
    status: str


class ExperimentItemCompareResponse(BaseModel):
    experiment_id: uuid.UUID
    baseline_experiment_id: uuid.UUID
    evaluator_id: uuid.UUID
    items: list[ItemComparisonRowResponse]


class CreateAppConfigRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    prompt: dict[str, Any] = Field(default_factory=dict)
    model: dict[str, Any] = Field(default_factory=dict)
    retrieval: dict[str, Any] = Field(default_factory=dict)


class AppConfigResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    version: int
    description: str | None
    prompt: dict[str, Any]
    model: dict[str, Any]
    retrieval: dict[str, Any]
    content_hash: str
    created_at: datetime


class SetAppConfigAliasRequest(BaseModel):
    app_config_id: uuid.UUID


class AppConfigSummaryResponse(BaseModel):
    id: uuid.UUID
    name: str
    version: int


class AppConfigAliasResponse(BaseModel):
    name: str
    app_config_id: uuid.UUID
    updated_at: datetime
    app_config: AppConfigSummaryResponse


class SubmitLiveInteractionRequest(BaseModel):
    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    documents: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    external_id: str | None = Field(default=None, max_length=200)
    metrics_set_id: uuid.UUID | None = None


class LiveInteractionScoreResponse(BaseModel):
    id: uuid.UUID
    live_interaction_id: uuid.UUID
    evaluator_id: uuid.UUID | None
    kind: str
    score: float | None
    label: str | None
    explanation: str | None
    threshold: float | None
    created_at: datetime


class LiveReviewResponse(BaseModel):
    id: uuid.UUID
    live_interaction_id: uuid.UUID
    verdict: str
    note: str | None
    reviewer: str | None
    created_at: datetime


class LiveInteractionResponse(BaseModel):
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
    scores: list[LiveInteractionScoreResponse] = Field(default_factory=list)
    review: LiveReviewResponse | None = None


class UpsertLiveReviewRequest(BaseModel):
    verdict: str = Field(min_length=1, max_length=32)
    note: str | None = None
    reviewer: str | None = Field(default=None, max_length=200)


class PromoteLiveInteractionRequest(BaseModel):
    dataset_id: uuid.UUID
    expected_output: Any
    expected_doc_ids: list[str] | None = None
