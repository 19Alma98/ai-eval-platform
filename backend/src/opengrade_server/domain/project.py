from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(value: str) -> str:
    normalized = value.strip().lower()
    slug = _SLUG_RE.sub("-", normalized).strip("-")
    return slug or "project"


@dataclass(frozen=True, slots=True)
class Project:
    id: uuid.UUID
    name: str
    slug: str
    created_at: datetime
    # Days of production data (traces, live answers, scores, alert events) to keep;
    # None falls back to the server's RETENTION_DAYS (keep forever when unset).
    retention_days: int | None = None

    @classmethod
    def create(cls, name: str, slug: str | None = None) -> Project:
        cleaned_name = name.strip()
        if not cleaned_name:
            raise ValueError("Project name must not be empty")

        resolved_slug = slug.strip() if slug else slugify(cleaned_name)
        if not resolved_slug:
            raise ValueError("Project slug must not be empty")

        return cls(
            id=uuid.uuid4(),
            name=cleaned_name,
            slug=resolved_slug,
            created_at=datetime.now(UTC),
        )
