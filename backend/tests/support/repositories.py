from __future__ import annotations

import uuid

from aiobs.api.deps import get_evaluator_repository, get_metrics_pack_repository
from aiobs.domain.evaluator import Evaluator
from aiobs.domain.metrics_pack import MetricsPack


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


class InMemoryMetricsPackRepository:
    def __init__(self) -> None:
        self._by_project: dict[uuid.UUID, MetricsPack] = {}

    async def add(self, pack: MetricsPack) -> MetricsPack:
        self._by_project[pack.project_id] = pack
        return pack

    async def get_by_project_id(self, project_id: uuid.UUID) -> MetricsPack | None:
        return self._by_project.get(project_id)

    async def update(self, pack: MetricsPack) -> MetricsPack:
        self._by_project[pack.project_id] = pack
        return pack


def wire_metrics_pack_repos(app) -> tuple[InMemoryEvaluatorRepository, InMemoryMetricsPackRepository]:  # noqa: ANN001
    evaluators = InMemoryEvaluatorRepository()
    metrics_packs = InMemoryMetricsPackRepository()
    app.dependency_overrides[get_evaluator_repository] = lambda: evaluators
    app.dependency_overrides[get_metrics_pack_repository] = lambda: metrics_packs
    return evaluators, metrics_packs
