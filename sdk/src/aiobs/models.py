from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _ApiModel(BaseModel):
    """Base API model with dict-like access for backward-compatible callers."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    def __getitem__(self, key: str) -> Any:
        fields = type(self).model_fields
        if key in fields:
            return getattr(self, key)
        for name, field in fields.items():
            if field.alias == key:
                return getattr(self, name)
        extras = self.__pydantic_extra__ or {}
        if key in extras:
            return extras[key]
        raise KeyError(key)

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default

    def __contains__(self, key: object) -> bool:
        if not isinstance(key, str):
            return False
        try:
            self[key]
        except KeyError:
            return False
        return True


class HealthResponse(_ApiModel):
    status: str


class ProjectResponse(_ApiModel):
    id: str
    name: str
    slug: str
    created_at: datetime | str


class DatasetResponse(_ApiModel):
    id: str
    project_id: str
    name: str
    version: int = 1
    description: str | None = None
    task_type: str | None = None
    created_at: datetime | str | None = None


class DatasetItemResponse(_ApiModel):
    id: str
    dataset_id: str | None = None
    input: Any = None
    expected_output: Any | None = None
    actual_output: Any | None = None
    context: Any | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    source_trace_id: str | None = None
    source_span_id: str | None = None


class DatasetDetailResponse(DatasetResponse):
    items: list[DatasetItemResponse] = Field(default_factory=list)


class ImportDatasetItemErrorResponse(_ApiModel):
    row: int
    message: str


class ImportDatasetItemsResponse(_ApiModel):
    created: int
    errors: list[ImportDatasetItemErrorResponse] = Field(default_factory=list)


class ExperimentResponse(_ApiModel):
    id: str
    project_id: str | None = None
    name: str
    dataset_id: str | None = None
    experiment_model_config: dict[str, Any] = Field(default_factory=dict, alias="model_config")
    version: str | None = None
    baseline_experiment_id: str | None = None
    app_config_id: str | None = None
    metrics_set_id: str | None = None
    status: str | None = None
    created_at: datetime | str | None = None


class ExperimentItemOutputResponse(_ApiModel):
    id: str | None = None
    experiment_id: str | None = None
    dataset_item_id: str | None = None
    actual_output: Any | None = None
    context: Any | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    updated_at: datetime | str | None = None


class EvaluationResultResponse(_ApiModel):
    id: str | None = None
    run_id: str | None = None
    dataset_item_id: str | None = None
    score: float | None = None
    label: str | None = None
    explanation: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    duration_ms: int | None = None


class EvaluationRunResponse(_ApiModel):
    id: str
    experiment_id: str | None = None
    evaluator_id: str | None = None
    status: str
    started_at: datetime | str | None = None
    finished_at: datetime | str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    results: list[EvaluationResultResponse] = Field(default_factory=list)


class EvaluateResponse(_ApiModel):
    experiment: ExperimentResponse
    runs: list[EvaluationRunResponse] = Field(default_factory=list)


class EvaluatorSummaryResponse(_ApiModel):
    evaluator_id: str | None = None
    evaluator_name: str | None = None
    run_id: str | None = None
    status: str | None = None
    n_items: int | None = None
    n_scored: int | None = None
    n_error: int | None = None
    n_skipped: int | None = None
    mean_score: float | None = None
    pass_rate: float | None = None


class ExperimentSummaryResponse(_ApiModel):
    experiment_id: str
    evaluators: list[EvaluatorSummaryResponse] = Field(default_factory=list)


class MetricComparisonResponse(_ApiModel):
    evaluator_id: str | None = None
    evaluator_name: str | None = None
    metric: str | None = None
    candidate: float | None = None
    baseline: float | None = None
    delta: float | None = None
    status: str | None = None


class ExperimentCompareResponse(_ApiModel):
    experiment_id: str | None = None
    baseline_experiment_id: str | None = None
    metrics: list[MetricComparisonResponse] = Field(default_factory=list)
    regressions: list[MetricComparisonResponse] = Field(default_factory=list)
    improved: list[MetricComparisonResponse] = Field(default_factory=list)
    unchanged: list[MetricComparisonResponse] = Field(default_factory=list)
    config_mismatches: list[MetricComparisonResponse] = Field(default_factory=list)
    insufficient_n: list[MetricComparisonResponse] = Field(default_factory=list)


class MetricsPackEntryResponse(_ApiModel):
    kind: str
    enabled: bool | None = None
    threshold: float | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    evaluator_id: str | None = None
    removable: bool | None = None


class MetricsPackResponse(_ApiModel):
    id: str | None = None
    project_id: str | None = None
    entries: list[MetricsPackEntryResponse] = Field(default_factory=list)
    updated_at: datetime | str | None = None


class AppConfigPromptBody(_ApiModel):
    system: str | None = None
    user: str | None = None
    template: str | None = None


class AppConfigModelBody(_ApiModel):
    model_id: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None


class AppConfigRetrievalBody(_ApiModel):
    top_k: int | None = None
    index: str | None = None


class AppConfigResponse(_ApiModel):
    id: str
    project_id: str
    name: str
    version: int = 1
    description: str | None = None
    prompt: AppConfigPromptBody | dict[str, Any] = Field(default_factory=dict)
    model: AppConfigModelBody | dict[str, Any] = Field(default_factory=dict)
    retrieval: AppConfigRetrievalBody | dict[str, Any] = Field(default_factory=dict)
    content_hash: str = ""
    created_at: datetime | str | None = None


class AppConfigSummaryResponse(_ApiModel):
    id: str
    name: str
    version: int


class AppConfigAliasResponse(_ApiModel):
    name: str
    app_config_id: str
    updated_at: datetime | str
    app_config: AppConfigSummaryResponse


class LiveInteractionResponse(_ApiModel):
    id: str
    project_id: str | None = None
    question: str
    answer: str
    documents: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    external_id: str | None = None
    judge_status: str
    metrics_set_id: str | None = None
    score_warning: str | None = None
    error_message: str | None = None
    created_at: datetime | str | None = None
    scored_at: datetime | str | None = None
