from __future__ import annotations

import pytest
from httpx2 import AsyncClient

from aiobs_server.domain.live_interaction import LiveInteraction, LiveInteractionScore
from aiobs_server.domain.project import Project
from aiobs_server.infrastructure.db import get_session_factory
from aiobs_server.infrastructure.repositories import (
    SqlAlchemyLiveInteractionRepository,
    SqlAlchemyProjectRepository,
    SqlJudgeClaimCache,
)


@pytest.mark.asyncio
async def test_sql_claim_cache_roundtrip(client: AsyncClient) -> None:
    # The `client` fixture resets the schema and initialises the session factory.
    cache = SqlJudgeClaimCache()
    assert await cache.get("k1") is None
    await cache.put("k1", prompt_version="correctness.claims.v3", model="m", claims=["a", "b"])
    await cache.put("k1", prompt_version="correctness.claims.v3", model="m", claims=["zzz"])
    assert await cache.get("k1") == ["a", "b"]


@pytest.mark.asyncio
async def test_live_score_metadata_roundtrip(client: AsyncClient) -> None:
    metadata = {"claims": [{"text": "a", "verdict": "supported", "doc_ids": ["d1"]}]}
    factory = get_session_factory()
    async with factory() as session:
        project = await SqlAlchemyProjectRepository(session).add(
            Project.create("Live meta", slug="live-meta")
        )
        live = SqlAlchemyLiveInteractionRepository(session)
        interaction = await live.add(LiveInteraction.create(project.id, "q", "a"))
        await live.replace_scores(
            interaction.id,
            [
                LiveInteractionScore.create(
                    interaction.id, "groundedness", score=1.0, label="PASS", metadata=metadata
                )
            ],
        )
    async with factory() as session:
        scores = await SqlAlchemyLiveInteractionRepository(session).list_scores(interaction.id)
    assert [s.metadata for s in scores] == [metadata]
