from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from aiobs_server.infrastructure.models import Base
from aiobs_server.infrastructure.repositories import SqlAlchemyExperimentMetricRepository


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


async def test_upsert_merges_last_value_wins_and_isolates_experiments(
    session: AsyncSession,
) -> None:
    repo = SqlAlchemyExperimentMetricRepository(session)
    a, b = uuid.uuid4(), uuid.uuid4()

    assert await repo.get(a) == {}
    assert await repo.upsert(a, {"cost_usd": 1.0, "acc": 0.5}) == {"acc": 0.5, "cost_usd": 1.0}
    assert await repo.upsert(a, {"cost_usd": 2.0}) == {"acc": 0.5, "cost_usd": 2.0}
    assert await repo.upsert(b, {"cost_usd": 9.0}) == {"cost_usd": 9.0}
    assert await repo.get(a) == {"acc": 0.5, "cost_usd": 2.0}
    assert await repo.upsert(a, {}) == {"acc": 0.5, "cost_usd": 2.0}
