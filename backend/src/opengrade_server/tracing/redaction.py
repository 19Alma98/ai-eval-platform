"""Content capture / attribute redaction."""

from __future__ import annotations

from typing import Any

from aiobs_server.domain.trace import Span, Trace
from aiobs_server.tracing.openinference import CONTENT_ATTRIBUTE_KEYS


def redact_attributes(
    attributes: dict[str, Any], *, content_capture_enabled: bool
) -> dict[str, Any]:
    if content_capture_enabled:
        return dict(attributes)
    return {k: v for k, v in attributes.items() if k not in CONTENT_ATTRIBUTE_KEYS}


def redact_span(span: Span, *, content_capture_enabled: bool) -> Span:
    return Span(
        id=span.id,
        span_id=span.span_id,
        parent_span_id=span.parent_span_id,
        name=span.name,
        kind=span.kind,
        start_time=span.start_time,
        end_time=span.end_time,
        status=span.status,
        attributes=redact_attributes(
            span.attributes, content_capture_enabled=content_capture_enabled
        ),
        events=list(span.events),
    )


def redact_trace(trace: Trace, *, content_capture_enabled: bool) -> Trace:
    input_value = trace.input if content_capture_enabled else None
    output_value = trace.output if content_capture_enabled else None
    spans = tuple(
        redact_span(span, content_capture_enabled=content_capture_enabled) for span in trace.spans
    )
    return Trace(
        id=trace.id,
        project_id=trace.project_id,
        trace_id=trace.trace_id,
        name=trace.name,
        status=trace.status,
        start_time=trace.start_time,
        end_time=trace.end_time,
        input=input_value,
        output=output_value,
        metadata=dict(trace.metadata),
        environment=trace.environment,
        user_id=trace.user_id,
        session_id=trace.session_id,
        spans=spans,
    )
