"""Truncate oversized span attributes, events, and trace input/output."""

from __future__ import annotations

from typing import Any

from opengrade_server.domain.trace import Span, Trace


def truncate_value(value: Any, max_chars: int) -> Any:
    """Recursively truncate string leaves to ``max_chars`` characters."""
    if max_chars < 0:
        raise ValueError(f"max_chars must be >= 0, got {max_chars}")
    if isinstance(value, str):
        return value if len(value) <= max_chars else value[:max_chars]
    if isinstance(value, dict):
        return {key: truncate_value(item, max_chars) for key, item in value.items()}
    if isinstance(value, list):
        return [truncate_value(item, max_chars) for item in value]
    if isinstance(value, tuple):
        return tuple(truncate_value(item, max_chars) for item in value)
    return value


def _limit_span(span: Span, max_chars: int) -> Span:
    return Span(
        id=span.id,
        span_id=span.span_id,
        parent_span_id=span.parent_span_id,
        name=span.name,
        kind=span.kind,
        start_time=span.start_time,
        end_time=span.end_time,
        status=span.status,
        attributes=truncate_value(dict(span.attributes), max_chars),
        events=truncate_value(list(span.events), max_chars),
    )


def apply_span_attr_limits(trace: Trace, max_chars: int) -> Trace:
    """Return a copy of ``trace`` with oversized string fields truncated."""
    return Trace(
        id=trace.id,
        project_id=trace.project_id,
        trace_id=trace.trace_id,
        name=trace.name,
        status=trace.status,
        start_time=trace.start_time,
        end_time=trace.end_time,
        input=truncate_value(trace.input, max_chars) if trace.input is not None else None,
        output=truncate_value(trace.output, max_chars) if trace.output is not None else None,
        metadata=dict(trace.metadata),
        environment=trace.environment,
        version=trace.version,
        user_id=trace.user_id,
        session_id=trace.session_id,
        spans=tuple(_limit_span(span, max_chars) for span in trace.spans),
        tags=trace.tags,
    )
