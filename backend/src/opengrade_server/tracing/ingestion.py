"""High-level OTLP ingestion pipeline: decode → normalize → sample → limit → redact."""

from __future__ import annotations

import uuid

from opengrade_server.domain.trace import Trace
from opengrade_server.tracing.limits import apply_span_attr_limits
from opengrade_server.tracing.normalization import normalize_raw_spans
from opengrade_server.tracing.otel import decode_otlp_to_raw_spans
from opengrade_server.tracing.redaction import redact_trace
from opengrade_server.tracing.sampling import should_sample_trace_id


def ingest_otlp_payload(
    *,
    project_id: uuid.UUID,
    body: bytes,
    content_type: str | None,
    content_capture_enabled: bool = False,
    sample_rate: float = 1.0,
    max_span_attr_chars: int | None = None,
) -> list[Trace]:
    raw_spans = decode_otlp_to_raw_spans(body, content_type)
    traces = normalize_raw_spans(project_id, raw_spans)
    if sample_rate < 1.0:
        traces = [t for t in traces if should_sample_trace_id(t.trace_id, sample_rate)]
    if max_span_attr_chars is not None:
        traces = [apply_span_attr_limits(t, max_span_attr_chars) for t in traces]
    return [
        redact_trace(trace, content_capture_enabled=content_capture_enabled) for trace in traces
    ]
