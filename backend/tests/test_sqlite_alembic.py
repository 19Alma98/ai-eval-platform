"""SQLite bootstrap uses Alembic (upgrade + legacy stamp)."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

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
        assert version == "0018_experiment_git"
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
        assert version == "0018_experiment_git"
    finally:
        sync.dispose()
        await dispose_db()
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        get_settings.cache_clear()


def _default_index_sql(sync_url: str) -> str:
    engine = create_engine(sync_url)
    try:
        with engine.connect() as conn:
            return str(
                conn.execute(
                    text(
                        "SELECT sql FROM sqlite_master "
                        "WHERE name = 'uq_metrics_sets_one_project_default'"
                    )
                ).scalar()
            )
    finally:
        engine.dispose()


async def _bootstrap(db_path: Path) -> None:
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"
    get_settings.cache_clear()
    await dispose_db()
    init_db(get_settings())
    await bootstrap_schema()
    await dispose_db()


@pytest.mark.asyncio
async def test_sqlite_default_metrics_set_index_is_partial(tmp_path: Path) -> None:
    """One *default* metrics set per project, not one metrics set per project."""
    db_path = tmp_path / "partial.db"
    sync_url = f"sqlite:///{db_path}"
    previous = os.environ.get("DATABASE_URL")
    try:
        await _bootstrap(db_path)
        assert "WHERE" in _default_index_sql(sync_url).upper()

        # A DB migrated before 0016 has the full-table unique index: upgrade repairs it.
        engine = create_engine(sync_url)
        try:
            with engine.begin() as conn:
                conn.execute(text("DROP INDEX uq_metrics_sets_one_project_default"))
                conn.execute(
                    text(
                        "CREATE UNIQUE INDEX uq_metrics_sets_one_project_default "
                        "ON metrics_sets (project_id)"
                    )
                )
                conn.execute(
                    text("UPDATE alembic_version SET version_num = '0015_drop_live_reviews'")
                )
        finally:
            engine.dispose()
        await _bootstrap(db_path)
        assert "WHERE" in _default_index_sql(sync_url).upper()

        engine = create_engine(sync_url)
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO projects (id, name, slug, created_at) "
                        "VALUES ('p1', 'P', 'p', CURRENT_TIMESTAMP)"
                    )
                )
                for i, default in enumerate((1, 0, 0)):
                    conn.execute(
                        text(
                            "INSERT INTO metrics_sets (id, project_id, name, version, "
                            "is_project_default, created_at, updated_at) VALUES "
                            "(:id, 'p1', :name, 1, :d, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                        ),
                        {"id": f"m{i}", "name": f"set{i}", "d": default},
                    )
                with pytest.raises(IntegrityError):
                    conn.execute(
                        text(
                            "INSERT INTO metrics_sets (id, project_id, name, version, "
                            "is_project_default, created_at, updated_at) VALUES "
                            "('m9', 'p1', 'set9', 1, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                        )
                    )
        finally:
            engine.dispose()
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_migrations_keep_app_loggers_enabled(tmp_path: Path) -> None:
    app_logger = logging.getLogger("opengrade_server.api.errors")
    previous = os.environ.get("DATABASE_URL")
    try:
        await _bootstrap(tmp_path / "logs.db")
        assert app_logger.disabled is False
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        get_settings.cache_clear()
