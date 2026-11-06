"""LLM judge settings (admin only). Non-secret overlays in DB; API key via ``.env`` only."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from opengrade_server.application.llm_settings import (
    OVERLAY_FIELDS,
    DotenvWriteError,
    EffectiveLlmSettings,
    llm_settings_store,
)
from opengrade_server.evaluation.runtime import ensure_evaluators_registered

router = APIRouter(prefix="/api/v1/settings/llm", tags=["settings"])

Source = Literal["env", "db"]


class LlmSettingsResponse(BaseModel):
    model: str
    api_base: str | None
    timeout_seconds: float
    max_retries: int
    max_concurrency: int
    temperature: float
    seed: int | None
    api_key_set: bool
    sources: dict[str, Source]
    updated_at: datetime | None

    @classmethod
    def from_effective(cls, effective: EffectiveLlmSettings) -> LlmSettingsResponse:
        return cls(
            model=effective.model,
            api_base=effective.api_base,
            timeout_seconds=effective.timeout_seconds,
            max_retries=effective.max_retries,
            max_concurrency=effective.max_concurrency,
            temperature=effective.temperature,
            seed=effective.seed,
            api_key_set=effective.api_key_set,
            sources={k: effective.sources[k] for k in OVERLAY_FIELDS},
            updated_at=effective.updated_at,
        )


class LlmSettingsUpdateRequest(BaseModel):
    """Partial update. Omitted fields unchanged; ``null`` clears a DB overlay.

    ``api_key``: omitted = unchanged; string = write ``.env``; ``null`` = clear from ``.env``.
    """

    model_config = ConfigDict(extra="forbid")

    model: str | None = None
    api_base: str | None = None
    timeout_seconds: float | None = Field(default=None, gt=0)
    max_retries: int | None = Field(default=None, ge=0)
    max_concurrency: int | None = Field(default=None, ge=1)
    temperature: float | None = Field(default=None, ge=0, le=2)
    seed: int | None = None
    api_key: str | None = None

    @field_validator("model")
    @classmethod
    def _model_non_empty(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("model must not be empty")
        return value.strip() if isinstance(value, str) else value

    @field_validator("api_base")
    @classmethod
    def _strip_api_base(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("api_key")
    @classmethod
    def _strip_api_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("api_key must not be empty; send null to clear")
        return stripped


def _apply_runtime() -> None:
    ensure_evaluators_registered()


@router.get("", response_model=LlmSettingsResponse)
async def get_llm_settings() -> LlmSettingsResponse:
    effective = await llm_settings_store.get_effective()
    return LlmSettingsResponse.from_effective(effective)


@router.put("", response_model=LlmSettingsResponse)
async def put_llm_settings(body: LlmSettingsUpdateRequest) -> LlmSettingsResponse:
    data = body.model_dump(exclude_unset=True)
    api_key_update = False
    if "api_key" in data:
        api_key_update = True
        try:
            llm_settings_store.set_api_key(data.pop("api_key"))
        except DotenvWriteError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(exc),
            ) from exc

    overlay: dict[str, Any] = {k: data[k] for k in OVERLAY_FIELDS if k in data}
    if overlay:
        try:
            await llm_settings_store.update_overlay(overlay)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    if api_key_update and not overlay:
        # set_api_key already cleared the cache
        pass

    effective = await llm_settings_store.get_effective()
    _apply_runtime()
    return LlmSettingsResponse.from_effective(effective)


@router.post("/reset", response_model=LlmSettingsResponse)
async def reset_llm_settings() -> LlmSettingsResponse:
    """Clear DB overlays only. Does not modify ``LLM_API_KEY`` in ``.env``."""
    effective = await llm_settings_store.reset_overlays()
    _apply_runtime()
    return LlmSettingsResponse.from_effective(effective)
