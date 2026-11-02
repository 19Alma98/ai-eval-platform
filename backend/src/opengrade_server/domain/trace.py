from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class Span:
    id: uuid.UUID
    span_id: str
    parent_span_id: str | None
    name: str
    kind: str
    start_time: datetime
    end_time: datetime | None
    status: str
    attributes: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Trace:
    id: uuid.UUID
    project_id: uuid.UUID
    trace_id: str
    name: str
    status: str
    start_time: datetime
    end_time: datetime | None
    input: Any | None = None
    output: Any | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    environment: str | None = None
    user_id: str | None = None
    session_id: str | None = None
    spans: tuple[Span, ...] = ()
    # Release of the app that produced the trace (OTel resource ``service.version``).
    version: str | None = None
    # OpenInference ``tag.tags`` from any span of the trace (deduplicated, in order).
    tags: tuple[str, ...] = ()


# Trace attribute index keys: tags are stored under TAG_KEY, metadata under "metadata.<key>".
TAG_KEY = "tag"
METADATA_KEY_PREFIX = "metadata."
MAX_TRACE_TAGS = 50
MAX_TAG_CHARS = 200
MAX_METADATA_KEYS = 50
MAX_ATTRIBUTE_VALUE_CHARS = 500


def indexable_metadata(metadata: dict[str, Any]) -> dict[str, str]:
    """Metadata entries searchable as ``key:value``; ``_``-prefixed keys are internal."""
    out: dict[str, str] = {}
    for key, value in metadata.items():
        if not isinstance(key, str) or not key or key.startswith("_"):
            continue
        if value is None or isinstance(value, dict | list):
            continue
        if isinstance(value, bool):
            text = "true" if value else "false"
        else:
            text = str(value)
        out[key[:MAX_TAG_CHARS]] = text[:MAX_ATTRIBUTE_VALUE_CHARS]
    return out


def trace_attribute_pairs(trace: Trace) -> set[tuple[str, str]]:
    """``(key, value)`` rows of the trace attribute index (tags + scalar metadata)."""
    pairs = {(TAG_KEY, tag) for tag in trace.tags}
    pairs.update(
        (f"{METADATA_KEY_PREFIX}{key}", value)
        for key, value in indexable_metadata(trace.metadata).items()
    )
    return pairs
