from __future__ import annotations

import hashlib
import json
from typing import Any


def claim_cache_key(reference: Any, *, prompt_version: str, model: str) -> str:
    payload = json.dumps(
        [reference, prompt_version, model], sort_keys=True, ensure_ascii=False, default=str
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class InMemoryJudgeClaimCache:
    """Process-local cache; used when no database-backed cache is wired."""

    def __init__(self) -> None:
        self._rows: dict[str, list[str]] = {}

    async def get(self, key: str) -> list[str] | None:
        claims = self._rows.get(key)
        return list(claims) if claims is not None else None

    async def put(self, key: str, *, prompt_version: str, model: str, claims: list[str]) -> None:
        # First write wins, matching the SQL implementation's ON CONFLICT DO NOTHING.
        self._rows.setdefault(key, list(claims))
