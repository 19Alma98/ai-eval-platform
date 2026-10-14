from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


def compute_content_hash(
    prompt: dict[str, Any],
    model: dict[str, Any],
    retrieval: dict[str, Any],
) -> str:
    payload = {"prompt": prompt, "model": model, "retrieval": retrieval}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class AppConfig:
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    version: int
    description: str | None
    prompt: dict[str, Any]
    model: dict[str, Any]
    retrieval: dict[str, Any]
    content_hash: str
    created_at: datetime

    @classmethod
    def create(
        cls,
        project_id: uuid.UUID,
        name: str,
        *,
        version: int = 1,
        description: str | None = None,
        prompt: dict[str, Any] | None = None,
        model: dict[str, Any] | None = None,
        retrieval: dict[str, Any] | None = None,
    ) -> AppConfig:
        cleaned = name.strip()
        if not cleaned:
            raise ValueError("AppConfig name must not be empty")
        if version < 1:
            raise ValueError("AppConfig version must be >= 1")
        p = dict(prompt or {})
        m = dict(model or {})
        r = dict(retrieval or {})
        return cls(
            id=uuid.uuid4(),
            project_id=project_id,
            name=cleaned,
            version=version,
            description=description.strip() if description else None,
            prompt=p,
            model=m,
            retrieval=r,
            content_hash=compute_content_hash(p, m, r),
            created_at=datetime.now(UTC),
        )

    def to_snapshot(self) -> dict[str, Any]:
        return {
            "app_config_id": str(self.id),
            "name": self.name,
            "version": self.version,
            "content_hash": self.content_hash,
            "prompt": dict(self.prompt),
            "model": dict(self.model),
            "retrieval": dict(self.retrieval),
        }


@dataclass(frozen=True, slots=True)
class AppConfigAlias:
    project_id: uuid.UUID
    name: str
    app_config_id: uuid.UUID
    updated_at: datetime

    @classmethod
    def create(
        cls,
        project_id: uuid.UUID,
        name: str,
        app_config_id: uuid.UUID,
    ) -> AppConfigAlias:
        cleaned = name.strip()
        if not cleaned:
            raise ValueError("Alias name must not be empty")
        return cls(
            project_id=project_id,
            name=cleaned,
            app_config_id=app_config_id,
            updated_at=datetime.now(UTC),
        )
