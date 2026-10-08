from __future__ import annotations

import asyncio
import os
import re
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from aiobs.infrastructure.db import dispose_db, init_db
from aiobs.infrastructure.models import Base
from aiobs.main import create_app

DEFAULT_TEST_DATABASE_URL = "postgresql+asyncpg://aiobs:aiobs@localhost:5434/aiobs_test"
_DB_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def integration_database_url() -> str:
    return os.getenv("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL)


def _is_unreachable(exc: BaseException) -> bool:
    text_exc = str(exc).lower()
    return any(
        token in text_exc
        for token in (
            "connection refused",
            "connect call failed",
            "could not connect",
            "connection reset",
            "timeout",
            "network is unreachable",
            "name or service not known",
        )
    )


async def _ensure_database(url: str) -> None:
    parsed = make_url(url)
    db_name = parsed.database
    if db_name is None:
        return
    if not _DB_NAME_RE.match(db_name):
        raise ValueError(f"Unsafe database name: {db_name!r}")
    admin_url = parsed.set(database="postgres")
    engine = create_async_engine(
        admin_url.render_as_string(hide_password=False),
        isolation_level="AUTOCOMMIT",
        poolclass=NullPool,
    )
    try:
        async with engine.connect() as conn:
            exists = await conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": db_name},
            )
            if not exists:
                await conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    finally:
        await engine.dispose()
        await asyncio.sleep(0)


async def _reset_schema(url: str) -> None:
    engine = create_async_engine(url, pool_pre_ping=True, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
            await conn.run_sync(Base.metadata.create_all)
    finally:
        await engine.dispose()
        await asyncio.sleep(0)


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    url = integration_database_url()
    try:
        await _ensure_database(url)
        await _reset_schema(url)
    except Exception as exc:  # noqa: BLE001
        if _is_unreachable(exc):
            pytest.skip(f"PostgreSQL not reachable for integration tests: {exc}")
        raise

    previous_url = os.environ.get("DATABASE_URL")
    previous_capture = os.environ.get("CONTENT_CAPTURE_ENABLED")
    os.environ["DATABASE_URL"] = url
    os.environ["CONTENT_CAPTURE_ENABLED"] = "true"
    from aiobs.config import get_settings

    get_settings.cache_clear()
    await dispose_db()
    init_db(get_settings())

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    await dispose_db()
    if previous_url is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = previous_url
    if previous_capture is None:
        os.environ.pop("CONTENT_CAPTURE_ENABLED", None)
    else:
        os.environ["CONTENT_CAPTURE_ENABLED"] = previous_capture
    get_settings.cache_clear()
