from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from aiobs_server.regression.policy import META_KEYS

_LLM_JUDGE_KINDS = frozenset(
    {
        "answer_relevance",
        "groundedness",
        "correctness",
        "context_precision",
        "context_recall",
    }
)
_JUDGE_METHODS: dict[str, frozenset[str]] = {
    "groundedness": frozenset({"claims", "rubric"}),
    "correctness": frozenset({"claims", "rubric"}),
    "answer_relevance": frozenset({"rubric"}),
    "context_precision": frozenset({"claims", "rubric"}),
    "context_recall": frozenset({"claims", "rubric"}),
}


class CreateProjectRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str | None = Field(default=None, min_length=1, max_length=200)


class ProjectResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class HealthResponse(BaseModel):
    status: str


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


class ImportDatasetItemErrorResponse(BaseModel):
    row: int
    message: str


class ImportDatasetItemsResponse(BaseModel):
    created: int
    errors: list[ImportDatasetItemErrorResponse]


class LlmJudgeConfigBody(BaseModel):
    """Known LLM-judge config fields. Extra keys allowed for forward compatibility."""

    model_config = ConfigDict(extra="allow")

    kind: str | None = None
    method: str | None = None
    scoring: Literal["recall", "f1"] | None = None
    max_claims: int | None = Field(default=None, ge=1)
    model: str | None = None
    temperature: float | None = None
    k: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _check_method_for_kind(self) -> Self:
        kind = (self.kind or "").strip().lower()
        if not kind or kind not in _LLM_JUDGE_KINDS:
            return self
        if self.method is None:
            return self
        method = self.method.strip().lower()
        allowed = _JUDGE_METHODS[kind]
        if method not in allowed:
            raise ValueError(
                f"{kind} judge: method must be one of {sorted(allowed)}, got {method!r}"
            )
        return self


def _validate_judge_config(kind: str, config: dict[str, Any]) -> None:
    key = kind.strip().lower()
    if key not in _LLM_JUDGE_KINDS:
        return
    LlmJudgeConfigBody.model_validate({**config, "kind": key})


class CreateEvaluatorRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    type: str = Field(min_length=1, max_length=32)
    config: dict[str, Any]
    version: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def _validate_config(self) -> Self:
        kind = str(self.config.get("kind", ""))
        _validate_judge_config(kind, self.config)
        return self


class EvaluatorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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

    @model_validator(mode="after")
    def _validate_config(self) -> Self:
        _validate_judge_config(self.kind, self.config)
        return self


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

    @model_validator(mode="after")
    def _validate_config(self) -> Self:
        _validate_judge_config(self.kind, self.config)
        return self


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


class CompareRunRefResponse(BaseModel):
    evaluator_id: uuid.UUID
    run_id: uuid.UUID
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExperimentCompareResponse(BaseModel):
    experiment_id: uuid.UUID
    baseline_experiment_id: uuid.UUID
    metrics: list[MetricComparisonResponse]
    regressions: list[MetricComparisonResponse]
    improved: list[MetricComparisonResponse]
    unchanged: list[MetricComparisonResponse]
    # Evaluators whose candidate and baseline runs used different effective configs.
    config_mismatches: list[MetricComparisonResponse] = []
    insufficient_n: list[MetricComparisonResponse] = []
    candidate_runs: list[CompareRunRefResponse] = []
    baseline_runs: list[CompareRunRefResponse] = []


class AbsoluteMinRuleBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min: float


class LatencyRuleBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    p95_max_ms: float


class CostRuleBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_per_request_usd: float


class RegressionRuleBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_delta: float


class ReleasePolicyBody(BaseModel):
    """Release gate policy. Named evaluator keys map to ``{min: ...}`` via extras."""

    model_config = ConfigDict(extra="allow")

    latency: LatencyRuleBody | None = None
    cost: CostRuleBody | None = None
    regression: RegressionRuleBody | None = None
    # Optional meta keys (stripped before evaluation); accepted so they are not
    # treated as absolute-min evaluator rules.
    api_base_url: str | None = None
    base_url: str | None = None
    project_id: str | None = None
    experiment_id: str | None = None
    baseline_experiment_id: str | None = None

    @model_validator(mode="after")
    def _validate_rules(self) -> Self:
        extras = dict(self.__pydantic_extra__ or {})
        for key, value in extras.items():
            if key in META_KEYS:
                continue
            AbsoluteMinRuleBody.model_validate(value)
        has_rules = (
            bool(extras)
            or self.latency is not None
            or self.cost is not None
            or self.regression is not None
        )
        if not has_rules:
            raise ValueError("policy must define at least one rule")
        return self

    def to_raw_dict(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True)


class ReleaseCheckRequest(BaseModel):
    experiment_id: uuid.UUID
    policy: ReleasePolicyBody
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
    metadata: dict[str, Any] = Field(default_factory=dict)
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


class AppConfigPromptBody(BaseModel):
    model_config = ConfigDict(extra="allow")

    system: str | None = None
    user: str | None = None
    template: str | None = None


class AppConfigModelBody(BaseModel):
    model_config = ConfigDict(extra="allow")

    model_id: str | None = None
    temperature: float | None = None
    max_tokens: int | None = Field(default=None, ge=1)


class AppConfigRetrievalBody(BaseModel):
    model_config = ConfigDict(extra="allow")

    top_k: int | None = Field(default=None, ge=1)
    index: str | None = None


class CreateAppConfigRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    prompt: AppConfigPromptBody = Field(default_factory=AppConfigPromptBody)
    model: AppConfigModelBody = Field(default_factory=AppConfigModelBody)
    retrieval: AppConfigRetrievalBody = Field(default_factory=AppConfigRetrievalBody)


class AppConfigResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    version: int
    description: str | None
    prompt: AppConfigPromptBody
    model: AppConfigModelBody
    retrieval: AppConfigRetrievalBody
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


class LiveScoreReviewResponse(BaseModel):
    id: uuid.UUID
    live_interaction_score_id: uuid.UUID
    verdict: str
    corrected_explanation: str | None
    note: str | None
    reviewer: str | None
    created_at: datetime


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
    metadata: dict[str, Any] = Field(default_factory=dict)
    review: LiveScoreReviewResponse | None = None


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


class LiveJudgeWarningResponse(BaseModel):
    kind: str
    warnings: list[str]
    warning_detail: dict[str, Any]


class ListLiveInteractionsResponse(BaseModel):
    items: list[LiveInteractionResponse]
    judge_warnings: list[LiveJudgeWarningResponse] = Field(default_factory=list)


class UpsertLiveReviewRequest(BaseModel):
    verdict: str = Field(min_length=1, max_length=32)
    note: str | None = None
    reviewer: str | None = Field(default=None, max_length=200)


class UpsertLiveScoreReviewRequest(BaseModel):
    verdict: str = Field(min_length=1, max_length=32)
    corrected_explanation: str | None = None
    note: str | None = None
    reviewer: str | None = Field(default=None, max_length=200)


class JudgeCalibrationBucketResponse(BaseModel):
    kind: str
    model: str | None
    method: str | None
    prompt_version: str | None
    n_reviewed: int
    n_agree: int
    n_disagree: int
    agreement_rate: float
    n_explanation_edits: int
    explanation_edit_rate: float


class PromoteLiveInteractionRequest(BaseModel):
    dataset_id: uuid.UUID
    expected_output: Any
    expected_doc_ids: list[str] | None = None


class LiveSeriesBucketResponse(BaseModel):
    bucket_start: datetime
    n: int
    mean_score: float | None
    fail_rate: float | None


class LiveAttentionItemResponse(BaseModel):
    interaction_id: uuid.UUID
    question: str
    created_at: datetime
    reason: str


class LiveOverviewResponse(BaseModel):
    n_interactions: int
    n_failed: int
    n_pending: int
    mean_score: float | None
    fail_rate: float | None
    series: list[LiveSeriesBucketResponse]
    attention: list[LiveAttentionItemResponse]


class OverviewMetricsSetRefResponse(BaseModel):
    id: uuid.UUID
    name: str
    version: int
    is_default: bool


class OverviewExperimentRefResponse(BaseModel):
    id: uuid.UUID
    name: str
    status: str
    created_at: datetime
    baseline_experiment_id: uuid.UUID | None


class OverviewCompareMetricResponse(BaseModel):
    name: str
    metric: str
    candidate: float | None
    baseline: float | None
    delta: float | None
    status: str


class OverviewCompareResponse(BaseModel):
    candidate_experiment_id: uuid.UUID
    baseline_experiment_id: uuid.UUID
    metrics: list[OverviewCompareMetricResponse]


class OverviewRegressionResponse(BaseModel):
    name: str
    delta: float | None
    status: str


class OfflineOverviewResponse(BaseModel):
    n_datasets: int
    metrics_set: OverviewMetricsSetRefResponse | None
    reference_threshold: float | None
    latest_experiment: OverviewExperimentRefResponse | None
    release_ready: bool
    compare: OverviewCompareResponse | None
    regressions: list[OverviewRegressionResponse]


class CalibrationAlertResponse(BaseModel):
    kind: str
    agreement_rate: float
    n_reviewed: int


class ProjectOverviewResponse(BaseModel):
    generated_at: datetime
    since: datetime
    until: datetime
    live: LiveOverviewResponse
    offline: OfflineOverviewResponse
    calibration_alerts: list[CalibrationAlertResponse]
    warnings: list[str] = Field(default_factory=list)
