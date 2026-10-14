from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from httpx2 import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from opengrade_server.domain.trace_score import TraceScore
from opengrade_server.infrastructure.models import ProjectModel
from opengrade_server.infrastructure.repositories import SqlAlchemyTraceScoreRepository
from tests.support.postgres import integration_database_url

pytestmark = pytest.mark.integration

A = "aa" * 16
B = "bb" * 16


@pytest.fixture
async def session(client: AsyncClient) -> AsyncIterator[AsyncSession]:
    # `client` resets the schema and skips when Postgres is unreachable.
    engine = create_async_engine(integration_database_url(), poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


async def _project(session: AsyncSession) -> uuid.UUID:
    project_id = uuid.uuid4()
    session.add(ProjectModel(id=project_id, name="p", slug=f"p-{project_id}"))
    await session.commit()
    return project_id


async def test_upsert_last_write_wins_keeps_id_and_missing_author_key(
    session: AsyncSession,
) -> None:
    project = await _project(session)
    repo = SqlAlchemyTraceScoreRepository(session)
    first = TraceScore.create(
        project, A, "quality", value=0.2, label="FAIL", threshold=0.5, metadata={"v": 1}
    )
    assert await repo.upsert_many([first]) == 1
    second = TraceScore.create(
        project, A, "quality", value=0.9, label="PASS", threshold=0.5, metadata={"v": 2}
    )
    with_author = TraceScore.create(
        project, A, "user_feedback", value=1.0, source="human", author="u1"
    )
    anonymous = TraceScore.create(project, A, "user_feedback", value=0.0, source="human")
    assert await repo.upsert_many([second, with_author, anonymous]) == 3

    rows = (await repo.list_by_trace_ids(project, [A]))[A]
    assert [(r.name, r.author, r.value, r.label) for r in rows] == [
        ("quality", None, 0.9, "PASS"),
        ("user_feedback", None, 0.0, None),
        ("user_feedback", "u1", 1.0, None),
    ]
    assert rows[0].id == first.id
    assert rows[0].metadata == {"v": 2}
    assert rows[0].created_at == first.created_at
    assert rows[0].updated_at >= first.updated_at


async def test_duplicate_keys_in_one_batch_keep_the_last(session: AsyncSession) -> None:
    project = await _project(session)
    repo = SqlAlchemyTraceScoreRepository(session)
    batch = [
        TraceScore.create(project, A, "q", value=0.1),
        TraceScore.create(project, A, "q", value=0.7),
    ]
    assert await repo.upsert_many(batch) == 1
    assert [r.value for r in (await repo.list_by_trace_ids(project, [A]))[A]] == [0.7]


async def test_summarize_window_pass_rate_and_null_values(session: AsyncSession) -> None:
    project = await _project(session)
    repo = SqlAlchemyTraceScoreRepository(session)
    await repo.upsert_many(
        [
            TraceScore.create(project, A, "quality", value=1.0, label="PASS"),
            TraceScore.create(project, B, "quality", value=0.0, label="FAIL"),
            TraceScore.create(project, "cc" * 16, "quality", label="PASS"),
            TraceScore.create(project, A, "user_feedback", value=1.0, source="human"),
        ]
    )
    now = datetime.now(UTC)
    rows = await repo.summarize(
        project, since=now - timedelta(hours=1), until=now + timedelta(minutes=1)
    )
    assert [(r.name, r.source, r.count, r.mean) for r in rows] == [
        ("quality", "sdk", 3, 0.5),
        ("user_feedback", "human", 1, 1.0),
    ]
    assert rows[0].pass_rate == pytest.approx(2 / 3)
    assert rows[1].pass_rate is None
    later = await repo.summarize(
        project, since=now + timedelta(hours=1), until=now + timedelta(hours=2)
    )
    assert later == []
