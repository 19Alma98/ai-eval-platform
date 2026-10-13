from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from aiobs_server.domain.trace_score import TraceScore
from aiobs_server.infrastructure.models import Base
from aiobs_server.infrastructure.repositories import SqlAlchemyTraceScoreRepository

A = "aa" * 16
B = "bb" * 16


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


async def test_upsert_last_write_wins_per_key(session: AsyncSession) -> None:
    repo = SqlAlchemyTraceScoreRepository(session)
    project = uuid.uuid4()

    first = TraceScore.create(project, A, "quality", value=0.2, label="FAIL", threshold=0.5)
    assert await repo.upsert_many([first]) == 1
    second = TraceScore.create(project, A, "quality", value=0.9, label="PASS", threshold=0.5)
    feedback_u1 = TraceScore.create(
        project, A, "user_feedback", value=1.0, source="human", author="u1"
    )
    feedback_anon = TraceScore.create(project, A, "user_feedback", value=0.0, source="human")
    assert await repo.upsert_many([second, feedback_u1, feedback_anon]) == 3

    rows = (await repo.list_by_trace_ids(project, [A]))[A]
    assert [(r.name, r.author, r.value, r.label) for r in rows] == [
        ("quality", None, 0.9, "PASS"),
        ("user_feedback", None, 0.0, None),
        ("user_feedback", "u1", 1.0, None),
    ]
    assert rows[0].id == first.id  # upsert keeps the original row


async def test_duplicate_keys_in_one_batch_keep_the_last(session: AsyncSession) -> None:
    repo = SqlAlchemyTraceScoreRepository(session)
    project = uuid.uuid4()
    batch = [
        TraceScore.create(project, A, "q", value=0.1),
        TraceScore.create(project, A, "q", value=0.7),
    ]
    assert await repo.upsert_many(batch) == 1
    assert [r.value for r in (await repo.list_by_trace_ids(project, [A]))[A]] == [0.7]


async def test_list_by_trace_ids_groups_and_isolates_projects(session: AsyncSession) -> None:
    repo = SqlAlchemyTraceScoreRepository(session)
    p1, p2 = uuid.uuid4(), uuid.uuid4()
    await repo.upsert_many(
        [
            TraceScore.create(p1, A, "q", value=1.0, metadata={"k": "v"}),
            TraceScore.create(p1, B, "q", value=0.0),
            TraceScore.create(p2, A, "q", value=0.5),
        ]
    )
    found = await repo.list_by_trace_ids(p1, [A, B, "cc" * 16])
    assert sorted(found) == [A, B]
    assert found[A][0].metadata == {"k": "v"}
    assert await repo.list_by_trace_ids(p1, []) == {}


async def test_summarize_window_and_pass_rate(session: AsyncSession) -> None:
    repo = SqlAlchemyTraceScoreRepository(session)
    project = uuid.uuid4()
    await repo.upsert_many(
        [
            TraceScore.create(project, A, "quality", value=1.0, label="PASS"),
            TraceScore.create(project, B, "quality", value=0.0, label="FAIL"),
            TraceScore.create(project, A, "user_feedback", value=1.0, source="human"),
        ]
    )
    now = datetime.now(UTC)
    rows = await repo.summarize(
        project, since=now - timedelta(hours=1), until=now + timedelta(minutes=1)
    )
    assert [(r.name, r.source, r.count, r.mean, r.pass_rate) for r in rows] == [
        ("quality", "sdk", 2, 0.5, 0.5),
        ("user_feedback", "human", 1, 1.0, None),
    ]
    assert (
        await repo.summarize(
            project, since=now + timedelta(hours=1), until=now + timedelta(hours=2)
        )
        == []
    )
