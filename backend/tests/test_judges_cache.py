from __future__ import annotations

import pytest

from aiobs.evaluation.judges.cache import InMemoryJudgeClaimCache, claim_cache_key
from aiobs.infrastructure.repositories import SqlJudgeClaimCache


def test_key_is_stable_and_sensitive_to_inputs() -> None:
    base = claim_cache_key(["q", "gold"], prompt_version="correctness.claims.v3", model="m")
    assert base == claim_cache_key(["q", "gold"], prompt_version="correctness.claims.v3", model="m")
    assert len(base) == 64
    assert base != claim_cache_key(
        ["q", "gold2"], prompt_version="correctness.claims.v3", model="m"
    )
    assert base != claim_cache_key(["q", "gold"], prompt_version="correctness.claims.v4", model="m")
    assert base != claim_cache_key(
        ["q", "gold"], prompt_version="correctness.claims.v3", model="m2"
    )


@pytest.mark.asyncio
async def test_in_memory_cache_roundtrip_and_first_write_wins() -> None:
    cache = InMemoryJudgeClaimCache()
    assert await cache.get("k") is None
    await cache.put("k", prompt_version="pv", model="m", claims=["a"])
    await cache.put("k", prompt_version="pv", model="m", claims=["b"])
    claims = await cache.get("k")
    assert claims == ["a"]
    claims.append("mutated")
    assert await cache.get("k") == ["a"]


@pytest.mark.asyncio
async def test_sql_claim_cache_swallows_db_errors() -> None:
    class BrokenFactory:
        def __call__(self):
            raise RuntimeError("db down")

    cache = SqlJudgeClaimCache(session_factory=BrokenFactory())
    assert await cache.get("k") is None
    await cache.put("k", prompt_version="pv", model="m", claims=["a"])  # must not raise
