from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterator, Mapping
from typing import Any

_UPSERT_CHUNK = 100


def _sanitize_for_json(value: Any) -> Any:
    """Replace non-finite floats with None so payloads survive strict JSON encoders."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Mapping):
        return {k: _sanitize_for_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize_for_json(v) for v in value]
    return value


def _jsonable(value: Any) -> Any:
    """Round-trip through JSON so pydantic objects, numpy scalars etc. serialize."""
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    value = _sanitize_for_json(value)
    return json.loads(json.dumps(value, default=str, allow_nan=False))


_UPSERT_MAX_BYTES = 2 * 1024 * 1024  # under platform json_max_body_bytes (4 MiB)


def _chunk_by_bytes(
    items: list[Any],
    *,
    max_count: int,
    max_bytes: int,
) -> Iterator[list[Any]]:
    """Yield slices of ``items`` capped by count and approximate JSON byte size."""
    batch: list[Any] = []
    budget = 0
    for item in items:
        size = len(json.dumps(item, default=str, separators=(",", ":"), allow_nan=False).encode())
        if batch and (len(batch) >= max_count or budget + size > max_bytes):
            yield batch
            batch = []
            budget = 0
        batch.append(item)
        budget += size
    if batch:
        yield batch


def _digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
