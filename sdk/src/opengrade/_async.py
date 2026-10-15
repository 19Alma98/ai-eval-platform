"""Run coroutines from sync code on one shared background event loop."""

from __future__ import annotations

import asyncio
import os
import threading
from collections.abc import Awaitable

_LOOP: asyncio.AbstractEventLoop | None = None
_LOCK = threading.Lock()


def _loop() -> asyncio.AbstractEventLoop:
    global _LOOP
    with _LOCK:
        if _LOOP is None or _LOOP.is_closed():
            loop = asyncio.new_event_loop()
            threading.Thread(target=loop.run_forever, name="opengrade-async", daemon=True).start()
            _LOOP = loop
        return _LOOP


async def _await[T](awaitable: Awaitable[T]) -> T:
    return await awaitable


def run_sync[T](awaitable: Awaitable[T], timeout: float | None = None) -> T:
    """Block until ``awaitable`` finishes on the background loop and return its result.

    On ``timeout`` the coroutine is cancelled and ``TimeoutError`` is raised.
    """
    loop = _loop()
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    if running is loop:
        raise RuntimeError("run_sync() called from the opengrade background loop would deadlock")
    future = asyncio.run_coroutine_threadsafe(_await(awaitable), loop)
    try:
        return future.result(timeout)
    except TimeoutError:
        future.cancel()
        raise


def _after_fork_in_child() -> None:
    """Drop the inherited loop (no thread in the child) so the next call builds a fresh one."""
    global _LOOP, _LOCK
    _LOOP = None
    _LOCK = threading.Lock()


if hasattr(os, "register_at_fork"):  # not on Windows
    os.register_at_fork(after_in_child=_after_fork_in_child)
