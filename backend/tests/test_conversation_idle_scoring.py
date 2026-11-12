"""Idle conversation scorer: projects without session judges must not starve the others."""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from opengrade_server.application import conversations as conversations_app
from opengrade_server.application.evaluators import CreateEvaluator
from opengrade_server.application.metrics_sets import EnsureProjectDefaultMetricsSet
from opengrade_server.config import get_settings
from opengrade_server.domain.conversation import Conversation
from opengrade_server.domain.project import Project
from opengrade_server.evaluation import bootstrap_evaluators
from opengrade_server.infrastructure.conversation_repository import (
    SqlAlchemyConversationRepository,
)
from opengrade_server.infrastructure.db import bootstrap_schema, dispose_db, init_db
from opengrade_server.infrastructure.repositories import (
    SqlAlchemyEvaluatorRepository,
    SqlAlchemyMetricsSetRepository,
    SqlAlchemyProjectRepository,
)


class _NoLlm:
    async def complete(self, **_: object) -> str:  # pragma: no cover - never called
        raise AssertionError("the scorer is patched; no judge call expected")


@pytest.fixture
async def factory(
    tmp_path_factory: pytest.TempPathFactory,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    db_path = tmp_path_factory.mktemp("idle") / "opengrade.db"
    previous_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"
    get_settings.cache_clear()
    await dispose_db()
    session_factory = init_db(get_settings())
    await bootstrap_schema()
    bootstrap_evaluators(_NoLlm())
    yield session_factory
    await dispose_db()
    if previous_url is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = previous_url
    get_settings.cache_clear()


async def _seed(
    factory: async_sessionmaker[AsyncSession], *, n_disabled: int
) -> tuple[uuid.UUID, uuid.UUID]:
    """``n_disabled`` idle conversations in a project with session judges off (the default),
    older than one idle conversation in a project with ``resolution`` enabled."""
    old = datetime.now(UTC) - timedelta(hours=2)
    async with factory() as session:
        projects = SqlAlchemyProjectRepository(session)
        off = await projects.add(Project.create(name="judges off", slug="judges-off"))
        on = await projects.add(Project.create(name="judges on", slug="judges-on"))
        metrics = SqlAlchemyMetricsSetRepository(session)
        evaluators = SqlAlchemyEvaluatorRepository(session)
        ensure = EnsureProjectDefaultMetricsSet(
            metrics, evaluators, projects, CreateEvaluator(evaluators, projects)
        )
        default_on = await ensure.execute(on.id)
        await metrics.update(
            replace(
                default_on,
                entries=tuple(
                    replace(e, enabled=True) if e.kind == "resolution" else e
                    for e in default_on.entries
                ),
            )
        )
        conversations = SqlAlchemyConversationRepository(session)
        for i in range(n_disabled):
            at = old - timedelta(minutes=n_disabled - i)
            await conversations.upsert(
                Conversation.create(
                    off.id, f"off-{i}", turn_count=1, started_at=at, last_activity_at=at
                )
            )
        await conversations.upsert(
            Conversation.create(on.id, "on-0", turn_count=1, started_at=old, last_activity_at=old)
        )
        await session.commit()
    return off.id, on.id


@pytest.mark.asyncio
async def test_disabled_projects_do_not_starve_enabled_ones(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    await _seed(factory, n_disabled=25)  # more than one batch (limit=20)
    scored: list[str] = []

    async def fake_execute(
        self: conversations_app.ScoreConversation, project_id: uuid.UUID, session_id: str
    ) -> None:
        scored.append(session_id)

    with patch.object(conversations_app.ScoreConversation, "execute", fake_execute):
        await conversations_app.score_idle_conversations(idle_minutes=15, limit=20)

    assert scored == ["on-0"]


@pytest.mark.asyncio
async def test_disabled_project_conversations_stay_open(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    off_id, _ = await _seed(factory, n_disabled=3)

    async def fake_execute(
        self: conversations_app.ScoreConversation, project_id: uuid.UUID, session_id: str
    ) -> None:
        return None

    with patch.object(conversations_app.ScoreConversation, "execute", fake_execute):
        await conversations_app.score_idle_conversations(idle_minutes=15)

    async with factory() as session:
        repo = SqlAlchemyConversationRepository(session)
        for i in range(3):
            conv = await repo.get_by_session(off_id, f"off-{i}")
            assert conv is not None
            # Still open: enabling the judges later scores them.
            assert conv.judge_status == "open"
