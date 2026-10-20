"""Process-local tracked asyncio tasks for scoring (drainable on shutdown)."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Coroutine
from typing import Any

logger = logging.getLogger(__name__)

_tasks: set[asyncio.Task[Any]] = set()
_live_score_inflight = 0


def spawn(coro: Coroutine[Any, Any, None], *, name: str) -> asyncio.Task[Any]:
    """Schedule ``coro`` and retain the task until it finishes."""
    task = asyncio.create_task(coro, name=name)
    _tasks.add(task)

    def _done(t: asyncio.Task[Any]) -> None:
        _tasks.discard(t)
        if t.cancelled():
            return
        exc = t.exception()
        if exc is not None:
            logger.exception("Background task %s failed", name, exc_info=exc)

    task.add_done_callback(_done)
    return task


def spawn_live_score_coro(
    coro: Coroutine[Any, Any, None],
    *,
    interaction_id: uuid.UUID | str,
) -> asyncio.Task[Any]:
    """Spawn a live-score coroutine and track inflight depth for backpressure."""

    async def _wrapped() -> None:
        global _live_score_inflight
        _live_score_inflight += 1
        try:
            await coro
        finally:
            _live_score_inflight -= 1

    return spawn(_wrapped(), name=f"live-score-{interaction_id}")


def live_score_inflight() -> int:
    return _live_score_inflight


def pending_count() -> int:
    return len(_tasks)


def enqueue_live_score(interaction_id: uuid.UUID) -> None:
    """Fire-and-forget live scoring with drain + backpressure tracking."""
    from opengrade_server.application.live_interactions import schedule_live_score

    spawn_live_score_coro(schedule_live_score(interaction_id), interaction_id=interaction_id)


async def drain(*, timeout: float) -> None:
    """Wait for tracked tasks to finish, up to ``timeout`` seconds."""
    if not _tasks:
        return
    pending = set(_tasks)
    if timeout <= 0:
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        return
    _done, still = await asyncio.wait(pending, timeout=timeout)
    if still:
        logger.warning(
            "Shutdown drain timed out with %s background task(s) still running; cancelling",
            len(still),
        )
        for task in still:
            task.cancel()
        await asyncio.gather(*still, return_exceptions=True)
