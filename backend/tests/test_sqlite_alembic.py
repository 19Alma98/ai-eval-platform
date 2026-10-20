"""SQLite bootstrap uses Alembic (upgrade + legacy stamp)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

from opengrade_server.config import get_settings
from opengrade_server.infrastructure.db import (
    SQLITE_BUSY_TIMEOUT_MS,
    bootstrap_schema,
    dispose_db,
    init_db,
)
from opengrade_server.infrastructure.models import Base


@pytest.mark.asyncio
async def test_bootstrap_applies_alembic_on_fresh_sqlite(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "fresh.db"
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"
    get_settings.cache_clear()
    await dispose_db()
    init_db(get_settings())
    await bootstrap_schema()

    sync = create_engine(f"sqlite:///{db_path}")
    try:
        insp = inspect(sync)
        assert "projects" in insp.get_table_names()
        assert "alembic_version" in insp.get_table_names()
        with sync.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert version == "0015_drop_live_reviews"
        # Drift index from migration 0007 is present
        exp_indexes = {ix["name"] for ix in insp.get_indexes("experiments")}
        assert "ix_experiments_app_config_id" in exp_indexes
    finally:
        sync.dispose()
        await dispose_db()
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_file_sqlite_enables_wal_and_busy_timeout(tmp_path: Path) -> None:
    db_path = tmp_path / "wal.db"
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"
    get_settings.cache_clear()
    await dispose_db()
    factory = init_db(get_settings())
    try:
        async with factory() as session:
            journal = (await session.execute(text("PRAGMA journal_mode"))).scalar()
            busy = (await session.execute(text("PRAGMA busy_timeout"))).scalar()
        assert str(journal).lower() == "wal"
        assert int(busy) == SQLITE_BUSY_TIMEOUT_MS
    finally:
        await dispose_db()
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_bootstrap_stamps_legacy_create_all_db(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.db"
    sync_url = f"sqlite:///{db_path}"
    engine = create_engine(sync_url)
    try:
        Base.metadata.create_all(engine)
        assert "alembic_version" not in inspect(engine).get_table_names()
    finally:
        engine.dispose()

    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"
    get_settings.cache_clear()
    await dispose_db()
    init_db(get_settings())
    await bootstrap_schema()

    sync = create_engine(sync_url)
    try:
        with sync.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert version == "0015_drop_live_reviews"
    finally:
        sync.dispose()
        await dispose_db()
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        get_settings.cache_clear()
