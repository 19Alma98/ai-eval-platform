import asyncio
import zlib
from collections.abc import AsyncGenerator
from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool, StaticPool

from opengrade_server.config import DEFAULT_SQLITE_URL, Settings, get_settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None

# Session-level lock so concurrent replicas serialize Alembic upgrades.
MIGRATION_ADVISORY_LOCK_KEY = zlib.crc32(b"opengrade_migrations")
SQLITE_BUSY_TIMEOUT_MS = 5000

__all__ = [
    "DEFAULT_SQLITE_URL",
    "MIGRATION_ADVISORY_LOCK_KEY",
    "SQLITE_BUSY_TIMEOUT_MS",
    "bootstrap_schema",
    "check_db_ready",
    "dispose_db",
    "ensure_sqlite_parent_dir",
    "get_session",
    "get_session_factory",
    "init_db",
    "is_sqlite_url",
    "run_migrations",
    "try_get_session_factory",
]


def is_sqlite_url(url: str) -> bool:
    return url.startswith("sqlite:") or url.startswith("sqlite+")


def _is_memory_sqlite_url(url: str) -> bool:
    return is_sqlite_url(url) and ":memory:" in url


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


def _configure_sqlite_connection(dbapi_connection: object, *, file_backed: bool) -> None:
    cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
    cursor.execute("PRAGMA foreign_keys=ON")
    if file_backed:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
    cursor.close()


def init_db(settings: Settings | None = None) -> async_sessionmaker[AsyncSession]:
    global _engine, _session_factory
    if _engine is not None:
        raise RuntimeError("Database already initialized; call dispose_db() first")
    cfg = settings or get_settings()
    url = cfg.database_url
    ensure_sqlite_parent_dir(url)

    kwargs: dict[str, object] = {"pool_pre_ping": True}
    file_backed_sqlite = False
    if is_sqlite_url(url):
        file_backed_sqlite = not _is_memory_sqlite_url(url)
        if _is_memory_sqlite_url(url):
            kwargs["connect_args"] = {"check_same_thread": False}
            kwargs["poolclass"] = StaticPool
        else:
            kwargs["connect_args"] = {"check_same_thread": False}

    _engine = create_async_engine(url, **kwargs)

    if is_sqlite_url(url):

        @event.listens_for(_engine.sync_engine, "connect")
        def _sqlite_on_connect(dbapi_connection: object, _connection_record: object) -> None:
            _configure_sqlite_connection(dbapi_connection, file_backed=file_backed_sqlite)

    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _session_factory


def _alembic_config() -> Config:
    # backend/src/opengrade_server/infrastructure/db.py → backend/
    backend_root = Path(__file__).resolve().parents[3]
    ini_path = backend_root / "alembic.ini"
    cfg = Config(str(ini_path))
    cfg.set_main_option("sqlalchemy.url", get_settings().database_url)
    return cfg


def _sqlite_needs_legacy_stamp(connection: Connection) -> bool:
    """True when tables exist from old create_all but alembic_version is missing."""
    insp = inspect(connection)
    tables = set(insp.get_table_names())
    if "alembic_version" in tables:
        return False
    user_tables = {t for t in tables if not t.startswith("sqlite_")}
    return bool(user_tables)


def _migrate_sqlite(connection: Connection) -> None:
    from alembic import command

    cfg = _alembic_config()
    if _sqlite_needs_legacy_stamp(connection):
        # Existing local DBs were created with create_all. Stamp head so upgrade
        # is a no-op; future revisions apply. Stale DBs (schema behind models)
        # must be deleted and recreated.
        cfg.attributes["connection"] = connection
        command.stamp(cfg, "head")
    cfg.attributes["connection"] = connection
    command.upgrade(cfg, "head")


def _upgrade_alembic_on_connection(connection: Connection) -> None:
    from alembic import command

    cfg = _alembic_config()
    cfg.attributes["connection"] = connection
    command.upgrade(cfg, "head")


def _postgres_locked_upgrade(connection: Connection) -> None:
    """Hold a session advisory lock for the whole Alembic upgrade."""
    connection.execute(
        text("SELECT pg_advisory_lock(:key)"),
        {"key": MIGRATION_ADVISORY_LOCK_KEY},
    )
    connection.commit()
    try:
        _upgrade_alembic_on_connection(connection)
        connection.commit()
    finally:
        connection.execute(
            text("SELECT pg_advisory_unlock(:key)"),
            {"key": MIGRATION_ADVISORY_LOCK_KEY},
        )
        connection.commit()


def _sync_sqlite_url(url: str) -> str:
    if url.startswith("sqlite+aiosqlite:"):
        return "sqlite:" + url.removeprefix("sqlite+aiosqlite:")
    return url


async def _run_postgres_migrations(url: str) -> None:
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            await conn.run_sync(_postgres_locked_upgrade)
    finally:
        await engine.dispose()


def run_migrations(settings: Settings | None = None) -> None:
    """Apply Alembic upgrades. Postgres path serializes via advisory lock."""
    cfg = settings or get_settings()
    url = cfg.database_url
    if is_sqlite_url(url):
        ensure_sqlite_parent_dir(url)
        engine = create_engine(_sync_sqlite_url(url))
        try:
            with engine.connect() as conn:
                _migrate_sqlite(conn)
                conn.commit()
        finally:
            engine.dispose()
        return
    asyncio.run(_run_postgres_migrations(url))


async def bootstrap_schema() -> None:
    """Apply Alembic migrations for SQLite local mode. Postgres uses Docker entrypoint."""
    if _engine is None:
        raise RuntimeError("Database not initialized")
    if _engine.dialect.name != "sqlite":
        return

    async with _engine.connect() as conn:
        await conn.run_sync(_migrate_sqlite)
        await conn.execute(text("PRAGMA foreign_keys=ON"))
        await conn.commit()


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
    """Drain in-process scoring tasks, then dispose the engine."""
    global _engine, _session_factory
    from opengrade_server.application.background_tasks import drain

    try:
        timeout = float(get_settings().shutdown_grace_seconds)
    except Exception:
        timeout = 30.0
    await drain(timeout=timeout)

    engine = _engine
    _engine = None
    _session_factory = None
    if engine is not None:
        await engine.dispose()
        await asyncio.sleep(0)


async def check_db_ready() -> bool:
    """Return True when the process engine can run ``SELECT 1``."""
    if _engine is None:
        return False
    try:
        async with _engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
