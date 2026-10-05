from __future__ import annotations

import uuid

from aiobs.api.deps import (
    get_evaluator_repository,
    get_experiment_repository,
    get_metrics_set_repository,
)
from aiobs.domain.evaluator import Evaluator
from aiobs.domain.experiment import Experiment
from aiobs.domain.metrics_set import MetricsSet


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
            s.version
            for s in self._items.values()
            if s.project_id == project_id and s.name == name
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
    app.dependency_overrides[get_evaluator_repository] = lambda: evaluators
    app.dependency_overrides[get_metrics_set_repository] = lambda: metrics_sets
    app.dependency_overrides[get_experiment_repository] = lambda: experiments
    return evaluators, metrics_sets, experiments
