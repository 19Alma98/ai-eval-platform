"""Manage per-client API keys (``admin`` scope only, enforced by the auth middleware)."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from opengrade_server.application.api_keys import (
    ApiKeyNotFoundError,
    ApiKeyRecord,
    Scope,
    api_key_store,
)
from opengrade_server.config import get_settings

router = APIRouter(prefix="/api/v1/api-keys", tags=["api-keys"])


class ApiKeyResponse(BaseModel):
    id: uuid.UUID
    name: str
    scope: Scope
    prefix: str
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None

    @classmethod
    def from_record(cls, record: ApiKeyRecord) -> ApiKeyResponse:
        return cls(
            id=record.id,
            name=record.name,
            scope=record.scope,
            prefix=record.prefix,
            created_at=record.created_at,
            last_used_at=record.last_used_at,
            revoked_at=record.revoked_at,
        )


class CreatedApiKeyResponse(ApiKeyResponse):
    key: str = Field(description="The key itself. Shown only once: it is not stored.")


class CreateApiKeyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    scope: Scope


@router.get("", response_model=list[ApiKeyResponse])
async def list_api_keys() -> list[ApiKeyResponse]:
    return [ApiKeyResponse.from_record(r) for r in await api_key_store.list()]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=CreatedApiKeyResponse)
async def create_api_key(body: CreateApiKeyRequest) -> CreatedApiKeyResponse:
    if not get_settings().accepted_api_keys():
        # Keys would never be checked: the server is open without OPENGRADE_API_KEY.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="auth is off: set OPENGRADE_API_KEY on the server before creating keys",
        )
    record, key = await api_key_store.create(name=body.name.strip(), scope=body.scope)
    return CreatedApiKeyResponse(**ApiKeyResponse.from_record(record).model_dump(), key=key)


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(key_id: uuid.UUID) -> None:
    try:
        await api_key_store.revoke(key_id)
    except ApiKeyNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="API key not found"
        ) from exc
