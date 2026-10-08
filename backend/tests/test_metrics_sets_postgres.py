from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy.exc import IntegrityError

from aiobs.application.evaluators import CreateEvaluator
from aiobs.application.metrics_sets import (
    EnsureProjectDefaultMetricsSet,
    find_or_create_evaluator_for_entry,
)
from aiobs.domain.evaluator import Evaluator
from aiobs.domain.metrics_set import MetricsSet, MetricsSetEntry
from aiobs.domain.project import Project
from aiobs.infrastructure.db import get_session_factory
from aiobs.infrastructure.repositories import (
    SqlAlchemyEvaluatorRepository,
    SqlAlchemyMetricsSetRepository,
    SqlAlchemyProjectRepository,
)

pytestmark = pytest.mark.integration


class _HideDefaultOnce:
    """Forces Ensure down the add path even though a default already exists."""

    def __init__(self, inner: SqlAlchemyMetricsSetRepository) -> None:
        self._inner = inner
        self._hide = True

    async def get_project_default(self, project_id: UUID) -> MetricsSet | None:
        if self._hide:
            self._hide = False
            return None
        return await self._inner.get_project_default(project_id)

    async def add(self, metrics_set: MetricsSet) -> MetricsSet:
        return await self._inner.add(metrics_set)

    async def update(self, metrics_set: MetricsSet) -> MetricsSet:
        return await self._inner.update(metrics_set)

    async def get_by_id(self, metrics_set_id: UUID) -> MetricsSet | None:
        return await self._inner.get_by_id(metrics_set_id)

    async def list_by_project(self, project_id: UUID) -> list[MetricsSet]:
        return await self._inner.list_by_project(project_id)


class _HideEvaluatorsOnce:
    """Forces find_or_create to attempt create against an existing unique row."""

    def __init__(self, inner: SqlAlchemyEvaluatorRepository) -> None:
        self._inner = inner
        self._hide = True

    async def list_by_project(self, project_id: UUID) -> list[Evaluator]:
        if self._hide:
            self._hide = False
            return []
        return await self._inner.list_by_project(project_id)

    async def add(self, evaluator: Evaluator) -> Evaluator:
        return await self._inner.add(evaluator)

    async def get_by_id(self, evaluator_id: UUID) -> Evaluator | None:
        return await self._inner.get_by_id(evaluator_id)


def _entry(kind: str, **config: Any) -> MetricsSetEntry:
    return MetricsSetEntry(
        id=UUID("00000000-0000-4000-8000-0000000000aa"),
        kind=kind,
        enabled=True,
        threshold=0.8,
        config=dict(config),
        evaluator_id=None,
        is_default=True,
    )


@pytest.mark.asyncio
async def test_ensure_default_recovers_from_real_integrity_error(client: AsyncClient) -> None:
    factory = get_session_factory()
    async with factory() as session:
        projects = SqlAlchemyProjectRepository(session)
        sets = SqlAlchemyMetricsSetRepository(session)
        evaluators = SqlAlchemyEvaluatorRepository(session)
        project = await projects.add(Project.create("Default race", slug="default-race"))
        winner = await sets.add(MetricsSet.create_project_default(project.id))

        with pytest.raises(IntegrityError):
            await sets.add(MetricsSet.create_project_default(project.id))

        # Session must be usable after rollback (IntegrityError path in add).
        assert await sets.get_project_default(project.id) is not None

        result = await EnsureProjectDefaultMetricsSet(
            _HideDefaultOnce(sets),
            evaluators,
            projects,
            CreateEvaluator(evaluators, projects),
        ).execute(project.id)

        defaults = [s for s in await sets.list_by_project(project.id) if s.is_project_default]
        assert len(defaults) == 1
        assert result.id == winner.id
        assert all(e.evaluator_id is not None for e in result.entries)


@pytest.mark.asyncio
async def test_find_or_create_evaluator_recovers_from_real_integrity_error(
    client: AsyncClient,
) -> None:
    factory = get_session_factory()
    async with factory() as session:
        projects = SqlAlchemyProjectRepository(session)
        evaluators = SqlAlchemyEvaluatorRepository(session)
        project = await projects.add(Project.create("Eval race", slug="eval-race"))
        winner = await evaluators.add(
            Evaluator.create(
                project.id, "hit_at_k", "deterministic", {"kind": "hit_at_k", "k": 5}
            )
        )

        with pytest.raises(IntegrityError):
            await evaluators.add(
                Evaluator.create(
                    project.id, "hit_at_k", "deterministic", {"kind": "hit_at_k", "k": 5}
                )
            )
        assert await evaluators.get_by_id(winner.id) is not None

        hidden = _HideEvaluatorsOnce(evaluators)
        found = await find_or_create_evaluator_for_entry(
            hidden,
            CreateEvaluator(hidden, projects),
            project.id,
            _entry("hit_at_k", k=5),
        )
        assert found.id == winner.id


@pytest.mark.asyncio
async def test_concurrent_ensure_default_leaves_one_default(client: AsyncClient) -> None:
    factory = get_session_factory()
    async with factory() as session:
        project = await SqlAlchemyProjectRepository(session).add(
            Project.create("Concurrent default", slug="concurrent-default")
        )
        project_id = project.id

    async def _ensure() -> MetricsSet:
        async with factory() as session:
            projects = SqlAlchemyProjectRepository(session)
            sets = SqlAlchemyMetricsSetRepository(session)
            evaluators = SqlAlchemyEvaluatorRepository(session)
            return await EnsureProjectDefaultMetricsSet(
                sets,
                evaluators,
                projects,
                CreateEvaluator(evaluators, projects),
            ).execute(project_id)

    results = await asyncio.gather(*[_ensure() for _ in range(6)])
    assert {r.id for r in results}  # all succeeded
    assert len({r.id for r in results}) == 1

    async with factory() as session:
        defaults = [
            s
            for s in await SqlAlchemyMetricsSetRepository(session).list_by_project(project_id)
            if s.is_project_default
        ]
        evaluators = await SqlAlchemyEvaluatorRepository(session).list_by_project(project_id)
    assert len(defaults) == 1
    assert all(e.evaluator_id is not None for e in defaults[0].entries)
    assert len(evaluators) == len(defaults[0].entries)
