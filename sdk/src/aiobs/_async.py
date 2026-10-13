"""Run coroutines from sync code on one shared background event loop.

A long-lived loop (not ``asyncio.run`` per call) keeps async clients that bind to
their loop — e.g. the httpx clients inside Ragas/DeepEval judges — usable across
calls, and works when the caller already runs a loop (Jupyter).
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable

_LOOP: asyncio.AbstractEventLoop | None = None
_LOCK = threading.Lock()


def _loop() -> asyncio.AbstractEventLoop:
    global _LOOP
    with _LOCK:
        if _LOOP is None or _LOOP.is_closed():
            loop = asyncio.new_event_loop()
            threading.Thread(target=loop.run_forever, name="aiobs-async", daemon=True).start()
            _LOOP = loop
        return _LOOP


async def _await[T](awaitable: Awaitable[T]) -> T:
    return await awaitable


def run_sync[T](awaitable: Awaitable[T], timeout: float | None = None) -> T:
    """Block until ``awaitable`` finishes on the background loop and return its result."""
    loop = _loop()
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    if running is loop:
        raise RuntimeError("run_sync() called from the aiobs background loop would deadlock")
    return asyncio.run_coroutine_threadsafe(_await(awaitable), loop).result(timeout)
