from __future__ import annotations

import pytest
from httpx import AsyncClient

from aiobs.infrastructure.repositories import SqlJudgeClaimCache


@pytest.mark.asyncio
async def test_sql_claim_cache_roundtrip(client: AsyncClient) -> None:
    # The `client` fixture resets the schema and initialises the session factory.
    cache = SqlJudgeClaimCache()
    assert await cache.get("k1") is None
    await cache.put("k1", prompt_version="correctness.claims.v3", model="m", claims=["a", "b"])
    await cache.put("k1", prompt_version="correctness.claims.v3", model="m", claims=["zzz"])
    assert await cache.get("k1") == ["a", "b"]
