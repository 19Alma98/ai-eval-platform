"""OTLP ingest rate / concurrency / pending-score backpressure."""

from __future__ import annotations

import pytest

from opengrade_server.api.otlp_backpressure import OtlpBackpressure, OtlpRejected


@pytest.fixture
def gate() -> OtlpBackpressure:
    return OtlpBackpressure(
        rate_per_second=2.0,
        max_inflight=1,
        max_pending_scores=2,
        retry_after_seconds=3,
    )


@pytest.mark.asyncio
async def test_rate_limit_returns_429(gate: OtlpBackpressure) -> None:
    await gate.acquire(pending_scores=0)
    gate.release()
    await gate.acquire(pending_scores=0)
    gate.release()
    with pytest.raises(OtlpRejected) as exc:
        await gate.acquire(pending_scores=0)
    assert exc.value.status_code == 429
    assert exc.value.retry_after == 3


@pytest.mark.asyncio
async def test_inflight_cap_returns_503() -> None:
    wide = OtlpBackpressure(
        rate_per_second=1000.0,
        max_inflight=1,
        max_pending_scores=100,
        retry_after_seconds=2,
    )
    await wide.acquire(pending_scores=0)
    with pytest.raises(OtlpRejected) as exc:
        await wide.acquire(pending_scores=0)
    assert exc.value.status_code == 503
    assert exc.value.retry_after == 2
    wide.release()


@pytest.mark.asyncio
async def test_pending_scores_cap_returns_503() -> None:
    wide = OtlpBackpressure(
        rate_per_second=1000.0,
        max_inflight=10,
        max_pending_scores=2,
        retry_after_seconds=1,
    )
    with pytest.raises(OtlpRejected) as exc:
        await wide.acquire(pending_scores=2)
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_slot_releases_on_exit() -> None:
    gate = OtlpBackpressure(
        rate_per_second=1000.0,
        max_inflight=1,
        max_pending_scores=10,
        retry_after_seconds=1,
    )
    async with gate.slot(pending_scores=0):
        assert gate._held == 1
    assert gate._held == 0
