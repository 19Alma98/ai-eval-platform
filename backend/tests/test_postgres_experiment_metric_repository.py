from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from httpx2 import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from aiobs_server.infrastructure.models import DatasetModel, ExperimentModel, ProjectModel
from aiobs_server.infrastructure.repositories import SqlAlchemyExperimentMetricRepository
from tests.support.postgres import integration_database_url

pytestmark = pytest.mark.integration


@pytest.fixture
async def session(client: AsyncClient) -> AsyncIterator[AsyncSession]:
    # `client` resets the schema and skips when Postgres is unreachable.
    engine = create_async_engine(integration_database_url(), poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


async def _create_experiment(session: AsyncSession, project_id: uuid.UUID) -> uuid.UUID:
    dataset_id, experiment_id = uuid.uuid4(), uuid.uuid4()
    session.add(DatasetModel(id=dataset_id, project_id=project_id, name=f"ds-{dataset_id}"))
    await session.flush()
    session.add(
        ExperimentModel(id=experiment_id, project_id=project_id, name="exp", dataset_id=dataset_id)
    )
    await session.commit()
    return experiment_id


async def test_upsert_merges_last_value_wins_and_isolates_experiments(
    session: AsyncSession,
) -> None:
    project_id = uuid.uuid4()
    session.add(ProjectModel(id=project_id, name="p", slug=f"p-{project_id}"))
    await session.commit()
    a = await _create_experiment(session, project_id)
    b = await _create_experiment(session, project_id)
    repo = SqlAlchemyExperimentMetricRepository(session)

    assert await repo.get(a) == {}
    assert await repo.upsert(a, {"cost_usd": 1.0, "acc": 0.5}) == {"acc": 0.5, "cost_usd": 1.0}
    assert await repo.upsert(a, {"cost_usd": 2.0}) == {"acc": 0.5, "cost_usd": 2.0}
    assert await repo.upsert(a, {}) == {"acc": 0.5, "cost_usd": 2.0}
    assert await repo.upsert(b, {"cost_usd": 9.0}) == {"cost_usd": 9.0}
    assert await repo.get(a) == {"acc": 0.5, "cost_usd": 2.0}
