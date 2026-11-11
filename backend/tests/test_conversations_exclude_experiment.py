from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from opengrade_server.application.conversations import (
    ConversationNotFoundError,
    GetConversation,
    refresh_conversation_from_trace,
)
from opengrade_server.domain.project import Project
from opengrade_server.domain.trace import Span, Trace
from opengrade_server.infrastructure.conversation_repository import SqlAlchemyConversationRepository
from opengrade_server.infrastructure.models import Base
from opengrade_server.infrastructure.repositories import SqlAlchemyTraceRepository
from opengrade_server.tracing.run_binding import is_experiment_bound, production_session_traces
from tests.test_api_live_interactions import InMemoryLiveRepository, InMemoryProjectRepository

SINCE = datetime(2026, 1, 1, tzinfo=UTC)


def _span(*, attrs: dict | None = None, offset_s: int = 0) -> Span:
    start = SINCE + timedelta(seconds=offset_s)
    return Span(
        id=uuid.uuid4(),
        span_id=uuid.uuid4().hex[:16],
        parent_span_id=None,
        name="turn",
        kind="CHAIN",
        start_time=start,
        end_time=start + timedelta(milliseconds=50),
        status="ok",
        attributes=attrs or {},
    )


def _trace(
    project_id: uuid.UUID,
    *,
    session_id: str,
    offset_s: int = 0,
    experiment: bool = False,
    input_text: str = "hello",
) -> Trace:
    attrs: dict = {}
    if experiment:
        attrs = {
            "opengrade.experiment_id": str(uuid.uuid4()),
            "opengrade.dataset_item_id": str(uuid.uuid4()),
        }
    start = SINCE + timedelta(seconds=offset_s)
    return Trace(
        id=uuid.uuid4(),
        project_id=project_id,
        trace_id=uuid.uuid4().hex,
        name="opengrade.eval demo" if experiment else "support",
        status="ok",
        start_time=start,
        end_time=start + timedelta(milliseconds=50),
        input=input_text,
        output="answer",
        session_id=session_id,
        spans=(_span(attrs=attrs, offset_s=offset_s),),
    )


def test_is_experiment_bound_and_production_filter() -> None:
    project_id = uuid.uuid4()
    prod = _trace(project_id, session_id="chat-1", offset_s=0)
    eval_t = _trace(project_id, session_id="chat-1", offset_s=1, experiment=True)
    assert not is_experiment_bound(prod)
    assert is_experiment_bound(eval_t)
    assert production_session_traces([prod, eval_t]) == [prod]


class _Traces:
    def __init__(self, traces: list[Trace]) -> None:
        self._traces = traces

    async def list_by_session_with_spans(
        self,
        project_id: uuid.UUID,
        session_id: str,
        *,
        limit: int = 200,
    ) -> list[Trace]:
        rows = [
            t for t in self._traces if t.project_id == project_id and t.session_id == session_id
        ]
        rows.sort(key=lambda t: t.start_time)
        return rows[:limit]


class _EmptyConversations:
    async def get_by_session(self, project_id: uuid.UUID, session_id: str):
        return None

    async def list_scores(self, conversation_id: uuid.UUID):
        return []

    async def upsert(self, *args, **kwargs):
        raise AssertionError("eval-only refresh must not upsert")


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest.mark.asyncio
async def test_get_conversation_keeps_only_production_turns() -> None:
    projects = InMemoryProjectRepository()
    project = await projects.add(Project.create("Conv", slug="conv"))
    session_id = "chat-mixed"
    prod = _trace(project.id, session_id=session_id, offset_s=0, input_text="prod q")
    eval_t = _trace(
        project.id, session_id=session_id, offset_s=1, experiment=True, input_text="eval q"
    )
    detail = await GetConversation(
        projects, _EmptyConversations(), _Traces([prod, eval_t]), InMemoryLiveRepository()
    ).execute(project.id, session_id)
    assert detail.summary.turn_count == 1
    assert [t.question for t in detail.turns] == ["prod q"]


@pytest.mark.asyncio
async def test_get_conversation_only_eval_is_not_found() -> None:
    projects = InMemoryProjectRepository()
    project = await projects.add(Project.create("Conv2", slug="conv2"))
    session_id = "eval-only"
    eval_t = _trace(project.id, session_id=session_id, experiment=True)
    with pytest.raises(ConversationNotFoundError):
        await GetConversation(
            projects, _EmptyConversations(), _Traces([eval_t]), InMemoryLiveRepository()
        ).execute(project.id, session_id)


@pytest.mark.asyncio
async def test_list_summaries_excludes_experiment_bound(session: AsyncSession) -> None:
    project_id = uuid.uuid4()
    traces = SqlAlchemyTraceRepository(session)
    conversations = SqlAlchemyConversationRepository(session)

    await traces.upsert(_trace(project_id, session_id="prod-only", offset_s=0))
    await traces.upsert(_trace(project_id, session_id="mixed", offset_s=1, input_text="real"))
    await traces.upsert(
        _trace(project_id, session_id="mixed", offset_s=2, experiment=True, input_text="eval")
    )
    await traces.upsert(_trace(project_id, session_id="eval-only", offset_s=3, experiment=True))

    summaries = await conversations.list_summaries(project_id)
    by_session = {s.session_id: s for s in summaries}
    assert set(by_session) == {"prod-only", "mixed"}
    assert by_session["mixed"].turn_count == 1
    assert by_session["prod-only"].turn_count == 1
    assert "eval-only" not in by_session


@pytest.mark.asyncio
async def test_refresh_eval_only_does_not_upsert() -> None:
    project_id = uuid.uuid4()
    session_id = "eval-only"
    eval_t = _trace(project_id, session_id=session_id, experiment=True)
    conv = _EmptyConversations()
    await refresh_conversation_from_trace(conv, _Traces([eval_t]), project_id, session_id)
