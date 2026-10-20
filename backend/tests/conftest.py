"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest

from opengrade_server.config import get_settings
from opengrade_server.infrastructure.db import dispose_db

pytest_plugins = ["support.postgres"]


@pytest.fixture(autouse=True)
def _judge_prompt_snapshots_tmpdir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    """Keep local prompt-audit writes out of the repo during tests."""
    path = tmp_path / "judge_prompt_snapshots.json"
    monkeypatch.setenv("OPENGRADE_JUDGE_PROMPT_SNAPSHOTS", str(path))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
async def _dispose_db_engine() -> AsyncIterator[None]:
    """Drop any engine opened during a test (``dispose_db`` also drains scorings)."""
    yield
    await dispose_db()


@pytest.fixture(autouse=True)
def _reset_otlp_backpressure() -> Iterator[None]:
    from opengrade_server.api.otlp_backpressure import reset_otlp_backpressure_for_tests

    reset_otlp_backpressure_for_tests()
    yield
    reset_otlp_backpressure_for_tests()
