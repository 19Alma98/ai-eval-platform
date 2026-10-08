from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest
from httpx import AsyncClient

from aiobs.domain.live_interaction import LiveInteraction
from aiobs.domain.project import Project
from aiobs.infrastructure.db import get_session_factory
from aiobs.infrastructure.repositories import (
    SqlAlchemyLiveInteractionRepository,
    SqlAlchemyProjectRepository,
)

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_list_orders_by_created_at_then_id_and_pages_with_offset(
    client: AsyncClient,
) -> None:
    # `client` resets schema and wires DATABASE_URL / session factory.
    factory = get_session_factory()
    same_ts = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)
    # Lexicographic UUID order ≠ insertion order; id.desc() must stabilize pages.
    ids = [
        UUID("00000000-0000-4000-8000-000000000003"),
        UUID("00000000-0000-4000-8000-000000000001"),
        UUID("00000000-0000-4000-8000-000000000002"),
        UUID("00000000-0000-4000-8000-000000000004"),
    ]

    async with factory() as session:
        project = await SqlAlchemyProjectRepository(session).add(
            Project.create("Live page", slug="live-page")
        )
        live = SqlAlchemyLiveInteractionRepository(session)
        for i, interaction_id in enumerate(ids):
            await live.add(
                replace(
                    LiveInteraction.create(project.id, f"q{i}", "a"),
                    id=interaction_id,
                    created_at=same_ts,
                )
            )

        page0 = await live.list_by_project(project.id, limit=2, offset=0)
        page1 = await live.list_by_project(project.id, limit=2, offset=2)

    assert [row.id for row in page0] == [ids[3], ids[0]]
    assert [row.id for row in page1] == [ids[2], ids[1]]


@pytest.mark.asyncio
async def test_search_treats_percent_and_underscore_as_literals(client: AsyncClient) -> None:
    factory = get_session_factory()
    async with factory() as session:
        project = await SqlAlchemyProjectRepository(session).add(
            Project.create("Live search", slug="live-search")
        )
        live = SqlAlchemyLiveInteractionRepository(session)
        await live.add(LiveInteraction.create(project.id, "discount 50%_off today", "a"))
        await live.add(LiveInteraction.create(project.id, "discount 50Xoff today", "a"))
        await live.add(LiveInteraction.create(project.id, "unrelated", "a"))

        matched = await live.list_by_project(project.id, search="50%_off")

    assert [row.question for row in matched] == ["discount 50%_off today"]
