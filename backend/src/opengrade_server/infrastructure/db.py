import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from aiobs_server.config import DEFAULT_SQLITE_URL, Settings, get_settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None

__all__ = [
    "DEFAULT_SQLITE_URL",
    "bootstrap_schema",
    "dispose_db",
    "ensure_sqlite_parent_dir",
    "get_session",
    "get_session_factory",
    "init_db",
    "is_sqlite_url",
    "try_get_session_factory",
]


def is_sqlite_url(url: str) -> bool:
    return url.startswith("sqlite:") or url.startswith("sqlite+")


def ensure_sqlite_parent_dir(url: str) -> None:
    """Create parent directory for a file-backed SQLite URL when needed."""
    if not is_sqlite_url(url):
        return
    from sqlalchemy.engine.url import make_url

    database = make_url(url).database
    if not database or database == ":memory:" or database.startswith(":memory:"):
        return
    path = Path(database).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    path.parent.mkdir(parents=True, exist_ok=True)


def init_db(settings: Settings | None = None) -> async_sessionmaker[AsyncSession]:
    global _engine, _session_factory
    if _engine is not None:
        raise RuntimeError("Database already initialized; call dispose_db() first")
    cfg = settings or get_settings()
    url = cfg.database_url
    ensure_sqlite_parent_dir(url)

    kwargs: dict[str, object] = {"pool_pre_ping": True}
    if is_sqlite_url(url):
        if ":memory:" in url:
            kwargs["connect_args"] = {"check_same_thread": False}
            kwargs["poolclass"] = StaticPool
        else:
            kwargs["connect_args"] = {"check_same_thread": False}

    _engine = create_async_engine(url, **kwargs)

    if is_sqlite_url(url):

        @event.listens_for(_engine.sync_engine, "connect")
        def _sqlite_on_connect(dbapi_connection: object, _connection_record: object) -> None:
            cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _session_factory


async def bootstrap_schema() -> None:
    """Create tables for SQLite local mode. Postgres uses Alembic migrations."""
    if _engine is None:
        raise RuntimeError("Database not initialized")
    if _engine.dialect.name != "sqlite":
        return
    from aiobs_server.infrastructure.models import Base

    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("PRAGMA foreign_keys=ON"))


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        return init_db()
    return _session_factory


def try_get_session_factory() -> async_sessionmaker[AsyncSession] | None:
    """Return the factory only if ``init_db`` / app lifespan already ran.

    Unlike :func:`get_session_factory`, this never creates an engine. Background
    tasks use it so in-memory API tests (no lifespan DB) skip SQL work instead of
    leaking an undisposed asyncpg pool.
    """
    return _session_factory


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    factory = get_session_factory()
    async with factory() as session:
        yield session


async def dispose_db() -> None:
    global _engine, _session_factory
    engine = _engine
    _engine = None
    _session_factory = None
    if engine is not None:
        await engine.dispose()
        await asyncio.sleep(0)
