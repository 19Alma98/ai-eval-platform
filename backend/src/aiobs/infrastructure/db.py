import asyncio
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from aiobs.config import Settings, get_settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def init_db(settings: Settings | None = None) -> async_sessionmaker[AsyncSession]:
    global _engine, _session_factory
    if _engine is not None:
        raise RuntimeError("Database already initialized; call dispose_db() first")
    cfg = settings or get_settings()
    _engine = create_async_engine(cfg.database_url, pool_pre_ping=True)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _session_factory


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
