"""Effective LLM judge settings: env baseline + optional DB overlay; API key via ``.env`` only."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from opengrade_server.config import Settings, get_settings
from opengrade_server.infrastructure.db import try_get_session_factory
from opengrade_server.infrastructure.dotenv_key import (
    DotenvWriteError,
    apply_process_env,
    remove_env_key,
    upsert_env_key,
)
from opengrade_server.infrastructure.models import SystemLlmSettingsModel

Source = Literal["env", "db"]
LLM_API_KEY_ENV = "LLM_API_KEY"
SINGLETON_ID = 1

OVERLAY_FIELDS = (
    "model",
    "api_base",
    "timeout_seconds",
    "max_retries",
    "max_concurrency",
    "temperature",
    "seed",
)


@dataclass(frozen=True, slots=True)
class EffectiveLlmSettings:
    model: str
    api_key: str | None
    api_base: str | None
    timeout_seconds: float
    max_retries: int
    max_concurrency: int
    temperature: float
    seed: int | None
    sources: dict[str, Source]
    api_key_set: bool
    updated_at: datetime | None

    @classmethod
    def from_env(cls, settings: Settings) -> EffectiveLlmSettings:
        return cls(
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            api_base=settings.llm_api_base,
            timeout_seconds=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
            max_concurrency=settings.llm_max_concurrency,
            temperature=settings.llm_temperature,
            seed=settings.llm_seed,
            sources={name: "env" for name in OVERLAY_FIELDS},
            api_key_set=bool(settings.llm_api_key),
            updated_at=None,
        )


class LlmSettingsStore:
    """Load/merge/update the singleton LLM overlay. API key stays in ``.env`` / process env."""

    def __init__(self) -> None:
        self._cached: EffectiveLlmSettings | None = None

    def clear_cache(self) -> None:
        self._cached = None

    @staticmethod
    def _factory() -> async_sessionmaker[AsyncSession] | None:
        return try_get_session_factory()

    async def get_effective(self, settings: Settings | None = None) -> EffectiveLlmSettings:
        if self._cached is not None:
            return self._cached
        base = settings or get_settings()
        factory = self._factory()
        if factory is None:
            effective = EffectiveLlmSettings.from_env(base)
            self._cached = effective
            return effective
        async with factory() as session:
            row = await session.get(SystemLlmSettingsModel, SINGLETON_ID)
            effective = self._merge(base, row)
        self._cached = effective
        return effective

    def _merge(self, base: Settings, row: SystemLlmSettingsModel | None) -> EffectiveLlmSettings:
        env = EffectiveLlmSettings.from_env(base)
        if row is None:
            return env
        sources: dict[str, Source] = dict(env.sources)
        values: dict[str, Any] = {
            "model": env.model,
            "api_key": env.api_key,
            "api_base": env.api_base,
            "timeout_seconds": env.timeout_seconds,
            "max_retries": env.max_retries,
            "max_concurrency": env.max_concurrency,
            "temperature": env.temperature,
            "seed": env.seed,
        }
        for name in OVERLAY_FIELDS:
            overlay = getattr(row, name)
            if overlay is not None:
                values[name] = overlay
                sources[name] = "db"
        return EffectiveLlmSettings(
            model=values["model"],
            api_key=values["api_key"],
            api_base=values["api_base"],
            timeout_seconds=values["timeout_seconds"],
            max_retries=values["max_retries"],
            max_concurrency=values["max_concurrency"],
            temperature=values["temperature"],
            seed=values["seed"],
            sources=sources,
            api_key_set=bool(values["api_key"]),
            updated_at=row.updated_at,
        )

    async def _ensure_row(self, session: AsyncSession) -> SystemLlmSettingsModel:
        row = await session.get(SystemLlmSettingsModel, SINGLETON_ID)
        if row is None:
            row = SystemLlmSettingsModel(id=SINGLETON_ID)
            session.add(row)
            await session.flush()
        return row

    async def update_overlay(self, patch: dict[str, Any]) -> EffectiveLlmSettings:
        """Apply overlay changes. Keys present with ``None`` clear that override."""
        unknown = set(patch) - set(OVERLAY_FIELDS)
        if unknown:
            raise ValueError(f"Unknown LLM overlay fields: {sorted(unknown)}")
        factory = self._factory()
        if factory is None:
            raise RuntimeError("Database is not initialized")
        async with factory() as session:
            row = await self._ensure_row(session)
            for name, value in patch.items():
                setattr(row, name, value)
            row.updated_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(row)
            effective = self._merge(get_settings(), row)
        self._cached = effective
        return effective

    async def reset_overlays(self) -> EffectiveLlmSettings:
        factory = self._factory()
        if factory is None:
            raise RuntimeError("Database is not initialized")
        async with factory() as session:
            row = await session.get(SystemLlmSettingsModel, SINGLETON_ID)
            if row is not None:
                await session.delete(row)
                await session.commit()
        self.clear_cache()
        return await self.get_effective()

    def set_api_key(self, value: str | None) -> None:
        """Write or clear ``LLM_API_KEY`` in ``.env`` and the process environment."""
        if value is None:
            remove_env_key(LLM_API_KEY_ENV)
            apply_process_env(LLM_API_KEY_ENV, None)
        else:
            upsert_env_key(LLM_API_KEY_ENV, value)
            apply_process_env(LLM_API_KEY_ENV, value)
        get_settings.cache_clear()
        self.clear_cache()


llm_settings_store = LlmSettingsStore()


async def get_effective_llm_settings() -> EffectiveLlmSettings:
    return await llm_settings_store.get_effective()


# Sync path for LiteLlmClient hot path: use cached merge when available, else env-only.
# Callers that mutate settings invalidate the cache; lifespan warms it after DB init.


def get_effective_llm_settings_sync() -> EffectiveLlmSettings:
    cached = llm_settings_store._cached
    if cached is not None:
        return cached
    return EffectiveLlmSettings.from_env(get_settings())


__all__ = [
    "DotenvWriteError",
    "EffectiveLlmSettings",
    "LLM_API_KEY_ENV",
    "LlmSettingsStore",
    "OVERLAY_FIELDS",
    "Source",
    "get_effective_llm_settings",
    "get_effective_llm_settings_sync",
    "llm_settings_store",
]
