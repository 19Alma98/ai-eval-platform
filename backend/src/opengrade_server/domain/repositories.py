from __future__ import annotations

import uuid
from collections.abc import Collection
from datetime import datetime
from typing import Protocol

from opengrade_server.domain.app_config import AppConfig, AppConfigAlias
from opengrade_server.domain.dataset import Dataset, DatasetItem
from opengrade_server.domain.evaluation import EvaluationResultRecord, EvaluationRun
from opengrade_server.domain.evaluator import Evaluator
from opengrade_server.domain.experiment import Experiment
from opengrade_server.domain.experiment_output import ExperimentItemOutput
from opengrade_server.domain.live_interaction import (
    LiveInteraction,
    LiveInteractionScore,
    LiveScoreReview,
)
from opengrade_server.domain.live_overview import LiveInRangeResult
from opengrade_server.domain.metrics_set import MetricsSet
from opengrade_server.domain.project import Project
from opengrade_server.domain.trace import Trace
from opengrade_server.domain.trace_score import TraceScore, TraceScoreSummaryRow


class ProjectRepository(Protocol):
    async def add(self, project: Project) -> Project: ...

    async def get_by_id(self, project_id: uuid.UUID) -> Project | None: ...

    async def get_by_slug(self, slug: str) -> Project | None: ...

    async def list_all(self) -> list[Project]: ...

    async def delete(self, project_id: uuid.UUID) -> bool: ...


class TraceRepository(Protocol):
    async def upsert(self, trace: Trace) -> Trace: ...

    async def get_by_trace_id(self, project_id: uuid.UUID, trace_id: str) -> Trace | None: ...

    async def list_by_project(
        self,
        project_id: uuid.UUID,
        *,
        status: str | None = None,
        search: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        cursor_start_time: datetime | None = None,
        cursor_id: uuid.UUID | None = None,
        limit: int = 50,
    ) -> list[Trace]: ...

    async def list_with_spans_in_range(
        self,
        project_id: uuid.UUID,
        *,
        since: datetime,
        until: datetime,
        limit: int = 5000,
    ) -> list[Trace]: ...


class DatasetRepository(Protocol):
    async def add(self, dataset: Dataset) -> Dataset: ...

    async def get_by_id(self, dataset_id: uuid.UUID) -> Dataset | None: ...

    async def list_by_project(
        self,
        project_id: uuid.UUID,
        *,
        task_type: str | None = None,
    ) -> list[Dataset]: ...

    async def add_item(self, item: DatasetItem) -> DatasetItem: ...

    async def list_items(self, dataset_id: uuid.UUID) -> list[DatasetItem]: ...

    async def count_items(self, dataset_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]: ...

    async def get_item(self, item_id: uuid.UUID) -> DatasetItem | None: ...

    async def delete(self, dataset_id: uuid.UUID) -> bool: ...


class EvaluatorRepository(Protocol):
    async def add(self, evaluator: Evaluator) -> Evaluator: ...

    async def get_by_id(self, evaluator_id: uuid.UUID) -> Evaluator | None: ...

    async def list_by_project(self, project_id: uuid.UUID) -> list[Evaluator]: ...

    async def get_by_ids(self, evaluator_ids: list[uuid.UUID]) -> list[Evaluator]: ...


class AppConfigRepository(Protocol):
    async def add(self, config: AppConfig) -> AppConfig: ...

    async def get_by_id(self, app_config_id: uuid.UUID) -> AppConfig | None: ...

    async def list_by_project(
        self, project_id: uuid.UUID, *, name: str | None = None, latest_only: bool = False
    ) -> list[AppConfig]: ...

    async def list_versions(self, project_id: uuid.UUID, name: str) -> list[AppConfig]: ...

    async def next_version(self, project_id: uuid.UUID, name: str) -> int: ...

    async def set_alias(self, alias: AppConfigAlias) -> AppConfigAlias: ...

    async def get_alias(self, project_id: uuid.UUID, name: str) -> AppConfigAlias | None: ...

    async def list_aliases(self, project_id: uuid.UUID) -> list[AppConfigAlias]: ...

    async def delete_alias(self, project_id: uuid.UUID, name: str) -> bool: ...


class ExperimentRepository(Protocol):
    async def add(self, experiment: Experiment) -> Experiment: ...

    async def get_by_id(self, experiment_id: uuid.UUID) -> Experiment | None: ...

    async def list_by_project(self, project_id: uuid.UUID) -> list[Experiment]: ...

    async def list_by_status(self, status: str, *, limit: int = 500) -> list[Experiment]: ...

    async def update(self, experiment: Experiment) -> Experiment: ...

    async def try_mark_running(self, experiment_id: uuid.UUID) -> Experiment | None: ...

    async def count_by_metrics_set_id(self, metrics_set_id: uuid.UUID) -> int: ...


class ExperimentMetricRepository(Protocol):
    """Experiment-level scalars: one value per (experiment, key), last write wins."""

    async def get(self, experiment_id: uuid.UUID) -> dict[str, float]: ...

    async def upsert(
        self, experiment_id: uuid.UUID, metrics: dict[str, float]
    ) -> dict[str, float]: ...


class TraceScoreRepository(Protocol):
    """Scores per OTel trace; one row per (project, trace, name, source, author)."""

    async def upsert_many(self, scores: list[TraceScore]) -> int: ...

    async def list_by_trace_ids(
        self, project_id: uuid.UUID, trace_ids: list[str]
    ) -> dict[str, list[TraceScore]]: ...

    async def summarize(
        self, project_id: uuid.UUID, *, since: datetime, until: datetime
    ) -> list[TraceScoreSummaryRow]: ...


class MetricsSetRepository(Protocol):
    async def add(self, metrics_set: MetricsSet) -> MetricsSet: ...

    async def get_by_id(self, metrics_set_id: uuid.UUID) -> MetricsSet | None: ...

    async def get_project_default(self, project_id: uuid.UUID) -> MetricsSet | None: ...

    async def list_by_project(self, project_id: uuid.UUID) -> list[MetricsSet]: ...

    async def update(self, metrics_set: MetricsSet) -> MetricsSet: ...

    async def delete(self, metrics_set_id: uuid.UUID) -> None: ...

    async def next_version(self, project_id: uuid.UUID, name: str) -> int: ...


class EvaluationRunRepository(Protocol):
    async def add_run(self, run: EvaluationRun) -> EvaluationRun: ...

    async def update_run(self, run: EvaluationRun) -> EvaluationRun: ...

    async def get_run(self, run_id: uuid.UUID) -> EvaluationRun | None: ...

    async def list_runs_by_experiment(self, experiment_id: uuid.UUID) -> list[EvaluationRun]: ...

    async def list_run_ids_with_results(self, experiment_id: uuid.UUID) -> set[uuid.UUID]: ...

    async def add_result(self, result: EvaluationResultRecord) -> EvaluationResultRecord: ...

    async def list_results(self, run_id: uuid.UUID) -> list[EvaluationResultRecord]: ...

    async def add_results(
        self, results: list[EvaluationResultRecord]
    ) -> list[EvaluationResultRecord]: ...


class ExperimentItemOutputRepository(Protocol):
    async def upsert(self, output: ExperimentItemOutput) -> ExperimentItemOutput: ...

    async def upsert_many(
        self, outputs: list[ExperimentItemOutput]
    ) -> list[ExperimentItemOutput]: ...

    async def list_by_experiment(self, experiment_id: uuid.UUID) -> list[ExperimentItemOutput]: ...

    async def get(
        self, experiment_id: uuid.UUID, dataset_item_id: uuid.UUID
    ) -> ExperimentItemOutput | None: ...


class LiveInteractionRepository(Protocol):
    async def add(self, interaction: LiveInteraction) -> LiveInteraction: ...

    async def update(self, interaction: LiveInteraction) -> LiveInteraction: ...

    async def try_claim_for_scoring(self, interaction_id: uuid.UUID) -> LiveInteraction | None: ...

    async def rollback(self) -> None: ...

    async def get_by_id(self, interaction_id: uuid.UUID) -> LiveInteraction | None: ...

    async def get_by_external_id(
        self, project_id: uuid.UUID, external_id: str
    ) -> LiveInteraction | None: ...

    async def ids_by_external_ids(
        self, project_id: uuid.UUID, external_ids: list[str]
    ) -> dict[str, uuid.UUID]: ...

    async def list_by_project(
        self,
        project_id: uuid.UUID,
        *,
        judge_statuses: Collection[str] | None = None,
        search: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[LiveInteraction]: ...

    async def list_by_judge_statuses(
        self,
        statuses: frozenset[str] | set[str],
        *,
        limit: int = 500,
    ) -> list[LiveInteraction]: ...

    async def list_in_range(
        self,
        project_id: uuid.UUID,
        *,
        since: datetime,
        until: datetime,
        limit: int = 10_000,
    ) -> LiveInRangeResult: ...

    async def replace_scores(
        self, interaction_id: uuid.UUID, scores: list[LiveInteractionScore]
    ) -> list[LiveInteractionScore]: ...

    async def list_scores(self, interaction_id: uuid.UUID) -> list[LiveInteractionScore]: ...

    async def list_recent_scores_by_kind(
        self,
        project_id: uuid.UUID,
        *,
        limit_per_kind: int = 50,
    ) -> dict[str, list[LiveInteractionScore]]: ...

    async def get_score(self, score_id: uuid.UUID) -> LiveInteractionScore | None: ...

    async def upsert_score_review(self, review: LiveScoreReview) -> LiveScoreReview: ...

    async def get_score_review(self, score_id: uuid.UUID) -> LiveScoreReview | None: ...

    async def list_score_reviews_by_score_ids(
        self, score_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, LiveScoreReview]: ...

    async def list_calibration_rows(
        self,
        project_id: uuid.UUID,
        *,
        since: datetime,
    ) -> list[tuple[LiveInteractionScore, LiveScoreReview]]: ...


class JudgeClaimCacheRepository(Protocol):
    """Extracted reference claims, keyed by reference + prompt version + judge model."""

    async def get(self, key: str) -> list[str] | None: ...

    async def put(
        self, key: str, *, prompt_version: str, model: str, claims: list[str]
    ) -> None: ...
