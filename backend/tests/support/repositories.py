from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import datetime

from opengrade_server.api.deps import (
    get_app_config_repository,
    get_evaluation_run_repository,
    get_evaluator_repository,
    get_experiment_repository,
    get_metrics_set_repository,
)
from opengrade_server.domain.app_config import AppConfig, AppConfigAlias
from opengrade_server.domain.evaluation import EvaluationResultRecord, EvaluationRun
from opengrade_server.domain.evaluator import Evaluator
from opengrade_server.domain.experiment import Experiment
from opengrade_server.domain.metrics_set import MetricsSet
from opengrade_server.domain.trace_score import (
    TraceScore,
    TraceScoreSummaryRow,
    summarize_trace_scores,
)


class InMemoryAppConfigRepository:
    """Minimal stub so create-experiment does not open a SQL session."""

    def __init__(self) -> None:
        self._configs: dict[uuid.UUID, AppConfig] = {}
        self._aliases: dict[tuple[uuid.UUID, str], AppConfigAlias] = {}

    async def add(self, config: AppConfig) -> AppConfig:
        self._configs[config.id] = config
        return config

    async def get_by_id(self, app_config_id: uuid.UUID) -> AppConfig | None:
        return self._configs.get(app_config_id)

    async def list_by_project(
        self,
        project_id: uuid.UUID,
        *,
        name: str | None = None,
        latest_only: bool = False,
    ) -> list[AppConfig]:
        return []

    async def list_versions(self, project_id: uuid.UUID, name: str) -> list[AppConfig]:
        return []

    async def next_version(self, project_id: uuid.UUID, name: str) -> int:
        return 1

    async def set_alias(self, alias: AppConfigAlias) -> AppConfigAlias:
        self._aliases[(alias.project_id, alias.name)] = alias
        return alias

    async def get_alias(self, project_id: uuid.UUID, name: str) -> AppConfigAlias | None:
        return self._aliases.get((project_id, name))

    async def list_aliases(self, project_id: uuid.UUID) -> list[AppConfigAlias]:
        return []

    async def delete_alias(self, project_id: uuid.UUID, name: str) -> bool:
        return self._aliases.pop((project_id, name), None) is not None


class InMemoryEvaluatorRepository:
    def __init__(self) -> None:
        self._items: dict[uuid.UUID, Evaluator] = {}

    async def add(self, evaluator: Evaluator) -> Evaluator:
        self._items[evaluator.id] = evaluator
        return evaluator

    async def get_by_id(self, evaluator_id: uuid.UUID) -> Evaluator | None:
        return self._items.get(evaluator_id)

    async def list_by_project(self, project_id: uuid.UUID) -> list[Evaluator]:
        return [e for e in self._items.values() if e.project_id == project_id]

    async def get_by_ids(self, evaluator_ids: list[uuid.UUID]) -> list[Evaluator]:
        return [self._items[i] for i in evaluator_ids if i in self._items]


class InMemoryMetricsSetRepository:
    def __init__(self) -> None:
        self._items: dict[uuid.UUID, MetricsSet] = {}

    async def add(self, metrics_set: MetricsSet) -> MetricsSet:
        self._items[metrics_set.id] = metrics_set
        return metrics_set

    async def get_by_id(self, metrics_set_id: uuid.UUID) -> MetricsSet | None:
        return self._items.get(metrics_set_id)

    async def get_project_default(self, project_id: uuid.UUID) -> MetricsSet | None:
        for metrics_set in self._items.values():
            if metrics_set.project_id == project_id and metrics_set.is_project_default:
                return metrics_set
        return None

    async def list_by_project(self, project_id: uuid.UUID) -> list[MetricsSet]:
        return sorted(
            (s for s in self._items.values() if s.project_id == project_id),
            key=lambda s: s.created_at,
        )

    async def update(self, metrics_set: MetricsSet) -> MetricsSet:
        self._items[metrics_set.id] = metrics_set
        return metrics_set

    async def delete(self, metrics_set_id: uuid.UUID) -> None:
        self._items.pop(metrics_set_id, None)

    async def next_version(self, project_id: uuid.UUID, name: str) -> int:
        versions = [
            s.version for s in self._items.values() if s.project_id == project_id and s.name == name
        ]
        return (max(versions) if versions else 0) + 1


class InMemoryExperimentRepository:
    def __init__(self) -> None:
        self._items: dict[uuid.UUID, Experiment] = {}

    async def add(self, experiment: Experiment) -> Experiment:
        self._items[experiment.id] = experiment
        return experiment

    async def get_by_id(self, experiment_id: uuid.UUID) -> Experiment | None:
        return self._items.get(experiment_id)

    async def list_by_project(self, project_id: uuid.UUID) -> list[Experiment]:
        return [e for e in self._items.values() if e.project_id == project_id]

    async def list_by_status(self, status: str, *, limit: int = 500) -> list[Experiment]:
        rows = [e for e in self._items.values() if e.status == status]
        return rows[: max(1, min(limit, 2000))]

    async def update(self, experiment: Experiment) -> Experiment:
        self._items[experiment.id] = experiment
        return experiment

    async def count_by_metrics_set_id(self, metrics_set_id: uuid.UUID) -> int:
        return sum(1 for e in self._items.values() if e.metrics_set_id == metrics_set_id)


class InMemoryExperimentMetricRepository:
    def __init__(self) -> None:
        self._items: dict[uuid.UUID, dict[str, float]] = {}

    async def get(self, experiment_id: uuid.UUID) -> dict[str, float]:
        return dict(sorted(self._items.get(experiment_id, {}).items()))

    async def upsert(self, experiment_id: uuid.UUID, metrics: dict[str, float]) -> dict[str, float]:
        self._items.setdefault(experiment_id, {}).update(metrics)
        return await self.get(experiment_id)


class InMemoryEvaluationRunRepository:
    """Empty evaluation-run stub so dataset mutations do not open a SQL session."""

    def __init__(self) -> None:
        self._runs: dict[uuid.UUID, EvaluationRun] = {}
        self._results: dict[uuid.UUID, EvaluationResultRecord] = {}

    async def add_run(self, run: EvaluationRun) -> EvaluationRun:
        self._runs[run.id] = run
        return run

    async def update_run(self, run: EvaluationRun) -> EvaluationRun:
        self._runs[run.id] = run
        return run

    async def get_run(self, run_id: uuid.UUID) -> EvaluationRun | None:
        return self._runs.get(run_id)

    async def list_runs_by_experiment(self, experiment_id: uuid.UUID) -> list[EvaluationRun]:
        return [r for r in self._runs.values() if r.experiment_id == experiment_id]

    async def add_result(self, result: EvaluationResultRecord) -> EvaluationResultRecord:
        self._results[result.id] = result
        return result

    async def list_results(self, run_id: uuid.UUID) -> list[EvaluationResultRecord]:
        return [r for r in self._results.values() if r.run_id == run_id]

    async def add_results(
        self, results: list[EvaluationResultRecord]
    ) -> list[EvaluationResultRecord]:
        for result in results:
            self._results[result.id] = result
        return results


def wire_metrics_pack_repos(
    app,  # noqa: ANN001
) -> tuple[
    InMemoryEvaluatorRepository,
    InMemoryMetricsSetRepository,
    InMemoryExperimentRepository,
]:
    evaluators = InMemoryEvaluatorRepository()
    metrics_sets = InMemoryMetricsSetRepository()
    experiments = InMemoryExperimentRepository()
    app_configs = InMemoryAppConfigRepository()
    evaluation_runs = InMemoryEvaluationRunRepository()
    app.dependency_overrides[get_evaluator_repository] = lambda: evaluators
    app.dependency_overrides[get_metrics_set_repository] = lambda: metrics_sets
    app.dependency_overrides[get_experiment_repository] = lambda: experiments
    app.dependency_overrides[get_app_config_repository] = lambda: app_configs
    app.dependency_overrides[get_evaluation_run_repository] = lambda: evaluation_runs
    return evaluators, metrics_sets, experiments


class InMemoryTraceScoreRepository:
    def __init__(self) -> None:
        self._rows: dict[tuple[uuid.UUID, str, str, str, str], TraceScore] = {}
        self.list_calls = 0

    async def upsert_many(self, scores: list[TraceScore]) -> int:
        latest = {s.key: s for s in scores}
        for key, score in latest.items():
            existing = self._rows.get(key)
            if existing is not None:
                score = replace(score, id=existing.id, created_at=existing.created_at)
            self._rows[key] = score
        return len(latest)

    async def list_by_trace_ids(
        self, project_id: uuid.UUID, trace_ids: list[str]
    ) -> dict[str, list[TraceScore]]:
        self.list_calls += 1
        wanted = set(trace_ids)
        out: dict[str, list[TraceScore]] = {}
        for row in self._rows.values():
            if row.project_id == project_id and row.trace_id in wanted:
                out.setdefault(row.trace_id, []).append(row)
        for rows in out.values():
            rows.sort(key=lambda r: (r.name, r.source, r.author or ""))
        return out

    async def summarize(
        self, project_id: uuid.UUID, *, since: datetime, until: datetime
    ) -> list[TraceScoreSummaryRow]:
        return summarize_trace_scores(
            r
            for r in self._rows.values()
            if r.project_id == project_id and since <= r.updated_at <= until
        )
