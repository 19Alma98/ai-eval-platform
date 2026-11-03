"""Per-client API keys stored in the server's own database.

Keys look like ``og_<random>``; only their SHA-256 is stored (they are long random values,
so a slow password hash adds nothing). The plaintext is returned once, at creation.

Scopes:

- ``admin``: everything, including key management.
- ``read``: dashboard and every read-only request; no writes at all.
- ``ingest``: send traces, scores / feedback and live interactions; cannot open the UI.

The ``OPENGRADE_API_KEY`` env var stays the bootstrap ``admin`` key and turns auth on: without
it the server is open and keys in this table are not checked.
"""

from __future__ import annotations

import hashlib
import secrets
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, get_args

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from opengrade_server.infrastructure.db import try_get_session_factory
from opengrade_server.infrastructure.models import ApiKeyModel

Scope = Literal["admin", "read", "ingest"]
SCOPES: tuple[str, ...] = get_args(Scope)
KEY_PREFIX = "og_"
_DISPLAY_PREFIX_LEN = 10  # "og_" + 7 random chars, shown in the UI to tell keys apart
_CACHE_TTL_S = 30.0
_TOUCH_INTERVAL_S = 60.0


class ApiKeyNotFoundError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class ApiKeyRecord:
    id: uuid.UUID
    name: str
    scope: Scope
    prefix: str
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None

    @property
    def active(self) -> bool:
        return self.revoked_at is None


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def generate_key() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(32)


def _record(model: ApiKeyModel) -> ApiKeyRecord:
    scope = model.scope if model.scope in SCOPES else "read"
    return ApiKeyRecord(
        id=model.id,
        name=model.name,
        scope=scope,  # type: ignore[arg-type]
        prefix=model.prefix,
        created_at=model.created_at,
        last_used_at=model.last_used_at,
        revoked_at=model.revoked_at,
    )


class ApiKeyStore:
    """DB access for API keys with a short in-process cache for the auth hot path.

    A revoke through this store clears the cache at once; the TTL only bounds staleness
    for changes made by another process (e.g. the ``opengrade keys`` CLI).
    Single API replica, like the rest of the server.
    """

    def __init__(self) -> None:
        self._by_hash: dict[object, tuple[float, ApiKeyRecord | None]] = {}
        self._by_id: dict[object, tuple[float, ApiKeyRecord | None]] = {}
        self._touched: dict[uuid.UUID, float] = {}

    def clear_cache(self) -> None:
        self._by_hash.clear()
        self._by_id.clear()

    @staticmethod
    def _factory() -> async_sessionmaker[AsyncSession] | None:
        return try_get_session_factory()

    async def create(self, *, name: str, scope: Scope) -> tuple[ApiKeyRecord, str]:
        factory = self._require_factory()
        key = generate_key()
        model = ApiKeyModel(
            id=uuid.uuid4(),
            name=name,
            scope=scope,
            prefix=key[:_DISPLAY_PREFIX_LEN],
            key_hash=hash_key(key),
            created_at=datetime.now(UTC),
        )
        async with factory() as session:
            session.add(model)
            await session.commit()
        self.clear_cache()
        return _record(model), key

    async def list(self) -> list[ApiKeyRecord]:
        factory = self._require_factory()
        async with factory() as session:
            rows = await session.scalars(
                select(ApiKeyModel).order_by(ApiKeyModel.created_at.desc())
            )
            return [_record(row) for row in rows]

    async def revoke(self, key_id: uuid.UUID) -> ApiKeyRecord:
        factory = self._require_factory()
        async with factory() as session:
            model = await session.get(ApiKeyModel, key_id)
            if model is None:
                raise ApiKeyNotFoundError(str(key_id))
            if model.revoked_at is None:
                model.revoked_at = datetime.now(UTC)
                await session.commit()
            record = _record(model)
        self.clear_cache()
        return record

    async def find_by_key(self, key: str) -> ApiKeyRecord | None:
        """Active key matching ``key``, or ``None``. Touches ``last_used_at``."""
        if not key.startswith(KEY_PREFIX):
            return None
        digest = hash_key(key)
        record = await self._cached(self._by_hash, digest, ApiKeyModel.key_hash == digest)
        return await self._use(record)

    async def find_by_id(self, key_id: uuid.UUID) -> ApiKeyRecord | None:
        """Active key with ``key_id`` (UI session cookies), or ``None``."""
        record = await self._cached(self._by_id, key_id, ApiKeyModel.id == key_id)
        return await self._use(record)

    async def _cached(
        self,
        cache: dict[object, tuple[float, ApiKeyRecord | None]],
        cache_key: object,
        where: object,
    ) -> ApiKeyRecord | None:
        now = time.monotonic()
        hit = cache.get(cache_key)
        if hit is not None and now - hit[0] < _CACHE_TTL_S:
            return hit[1]
        factory = self._factory()
        if factory is None:  # no DB (in-memory API tests): only the env key works
            return None
        async with factory() as session:
            model = await session.scalar(select(ApiKeyModel).where(where))  # type: ignore[arg-type]
        record = _record(model) if model is not None else None
        if len(cache) > 10_000:  # bound memory under a flood of random keys
            cache.clear()
        cache[cache_key] = (now, record)
        return record

    async def _use(self, record: ApiKeyRecord | None) -> ApiKeyRecord | None:
        if record is None or not record.active:
            return None
        now = time.monotonic()
        if now - self._touched.get(record.id, float("-inf")) >= _TOUCH_INTERVAL_S:
            self._touched[record.id] = now
            factory = self._factory()
            if factory is not None:
                async with factory() as session:
                    await session.execute(
                        update(ApiKeyModel)
                        .where(ApiKeyModel.id == record.id)
                        .values(last_used_at=datetime.now(UTC))
                    )
                    await session.commit()
        return record

    def _require_factory(self) -> async_sessionmaker[AsyncSession]:
        factory = self._factory()
        if factory is None:
            from opengrade_server.infrastructure.db import get_session_factory

            return get_session_factory()
        return factory


api_key_store = ApiKeyStore()
