"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from aiobs.infrastructure.db import dispose_db

pytest_plugins = ["support.postgres"]


@pytest.fixture(autouse=True)
async def _dispose_db_engine() -> AsyncIterator[None]:
    """Drop any engine opened accidentally during a test (incomplete overrides)."""
    yield
    await dispose_db()
