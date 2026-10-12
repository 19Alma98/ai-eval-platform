"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest

from aiobs_server.config import get_settings
from aiobs_server.infrastructure.db import dispose_db

pytest_plugins = ["support.postgres"]


@pytest.fixture(autouse=True)
def _judge_prompt_snapshots_tmpdir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    """Keep local prompt-audit writes out of the repo during tests."""
    path = tmp_path / "judge_prompt_snapshots.json"
    monkeypatch.setenv("AIOBS_JUDGE_PROMPT_SNAPSHOTS", str(path))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
async def _dispose_db_engine() -> AsyncIterator[None]:
    """Drop any engine opened accidentally during a test (incomplete overrides)."""
    yield
    await dispose_db()
