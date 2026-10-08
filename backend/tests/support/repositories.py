from __future__ import annotations

import uuid

from aiobs.api.deps import (
    get_app_config_repository,
    get_evaluator_repository,
    get_experiment_repository,
    get_metrics_set_repository,
)
from aiobs.domain.app_config import AppConfig, AppConfigAlias
from aiobs.domain.evaluator import Evaluator
from aiobs.domain.experiment import Experiment
from aiobs.domain.metrics_set import MetricsSet


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

    async def update(self, experiment: Experiment) -> Experiment:
        self._items[experiment.id] = experiment
        return experiment

    async def count_by_metrics_set_id(self, metrics_set_id: uuid.UUID) -> int:
        return sum(1 for e in self._items.values() if e.metrics_set_id == metrics_set_id)


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
    app.dependency_overrides[get_evaluator_repository] = lambda: evaluators
    app.dependency_overrides[get_metrics_set_repository] = lambda: metrics_sets
    app.dependency_overrides[get_experiment_repository] = lambda: experiments
    app.dependency_overrides[get_app_config_repository] = lambda: app_configs
    return evaluators, metrics_sets, experiments
