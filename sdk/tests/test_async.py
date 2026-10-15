from __future__ import annotations

import asyncio

import pytest

from opengrade import _async
from opengrade._async import run_sync


async def _value(x: int) -> int:
    await asyncio.sleep(0)
    return x


async def _boom() -> None:
    raise ValueError("bad")


async def _current_loop() -> asyncio.AbstractEventLoop:
    return asyncio.get_running_loop()


def test_returns_result() -> None:
    assert run_sync(_value(3)) == 3


def test_propagates_exception() -> None:
    with pytest.raises(ValueError, match="bad"):
        run_sync(_boom())


def test_reuses_one_loop_across_calls() -> None:
    assert run_sync(_current_loop()) is run_sync(_current_loop())


def test_works_when_caller_already_runs_a_loop() -> None:
    async def main() -> int:
        return run_sync(_value(7))  # e.g. a sync metric called from Jupyter

    assert asyncio.run(main()) == 7


def test_after_fork_hook_resets_loop() -> None:
    parent_loop = run_sync(_current_loop())
    _async._after_fork_in_child()
    assert _async._LOOP is None
    child_loop = run_sync(_current_loop())
    assert child_loop is not parent_loop
