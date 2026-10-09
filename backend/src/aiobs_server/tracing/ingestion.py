"""High-level OTLP ingestion pipeline: decode → normalize → redact."""

from __future__ import annotations

import uuid

from aiobs_server.domain.trace import Trace
from aiobs_server.tracing.normalization import normalize_raw_spans
from aiobs_server.tracing.otel import decode_otlp_to_raw_spans
from aiobs_server.tracing.redaction import redact_trace


def ingest_otlp_payload(
    *,
    project_id: uuid.UUID,
    body: bytes,
    content_type: str | None,
    content_capture_enabled: bool = False,
) -> list[Trace]:
    raw_spans = decode_otlp_to_raw_spans(body, content_type)
    traces = normalize_raw_spans(project_id, raw_spans)
    return [
        redact_trace(trace, content_capture_enabled=content_capture_enabled) for trace in traces
    ]
