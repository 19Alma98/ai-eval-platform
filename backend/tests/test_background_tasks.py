"""Shared background task spawn / drain."""

from __future__ import annotations

import asyncio

import pytest

from opengrade_server.application import background_tasks as bt


@pytest.fixture(autouse=True)
def _clear_tasks() -> None:
    bt._tasks.clear()
    yield
    bt._tasks.clear()


@pytest.mark.asyncio
async def test_spawn_and_drain_waits_until_done() -> None:
    done = asyncio.Event()

    async def work() -> None:
        await asyncio.sleep(0.05)
        done.set()

    bt.spawn(work(), name="test-work")
    assert len(bt._tasks) == 1
    await bt.drain(timeout=2.0)
    assert done.is_set()
    assert len(bt._tasks) == 0


@pytest.mark.asyncio
async def test_drain_timeout_cancels_running_task() -> None:
    started = asyncio.Event()

    async def slow() -> None:
        started.set()
        await asyncio.sleep(10)

    bt.spawn(slow(), name="slow")
    await started.wait()
    await bt.drain(timeout=0.05)
    assert len(bt._tasks) == 0


@pytest.mark.asyncio
async def test_live_score_inflight_tracks_spawn() -> None:
    gate = asyncio.Event()

    async def hold() -> None:
        await gate.wait()

    assert bt.live_score_inflight() == 0
    bt.spawn_live_score_coro(hold(), interaction_id="x")
    await asyncio.sleep(0)
    assert bt.live_score_inflight() == 1
    gate.set()
    await bt.drain(timeout=1.0)
    assert bt.live_score_inflight() == 0
