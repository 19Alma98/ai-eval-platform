"""Normalize raw OTLP spans into domain Trace trees."""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from aiobs_server.domain.trace import Span, Trace
from aiobs_server.tracing.openinference import extract_model_provider, resolve_span_kind


def _pick_trace_name(spans: list[dict[str, Any]]) -> str:
    roots = [s for s in spans if not s.get("parent_span_id")]
    candidates = roots or spans
    # Prefer LLM / CHAIN names when present
    for preferred in ("CHAIN", "LLM", "AGENT"):
        for span in candidates:
            kind = resolve_span_kind(span.get("attributes") or {})
            if kind == preferred and span.get("name"):
                return str(span["name"])
    name = candidates[0].get("name") if candidates else None
    return str(name) if name else "trace"


def _aggregate_status(spans: list[dict[str, Any]]) -> str:
    statuses = {s.get("status") or "unset" for s in spans}
    if "error" in statuses:
        return "error"
    if "ok" in statuses:
        return "ok"
    return "unset"


def _min_max_times(
    spans: list[dict[str, Any]],
) -> tuple[datetime, datetime | None]:
    starts = [s["start_time"] for s in spans if s.get("start_time") is not None]
    ends = [s["end_time"] for s in spans if s.get("end_time") is not None]
    if not starts:
        now = datetime.now(UTC)
        return now, None
    start = min(starts)
    end = max(ends) if ends else None
    return start, end


def _extract_trace_io(spans: list[Span]) -> tuple[Any | None, Any | None]:
    """Lift OpenInference input/output from the preferred root (CHAIN) span."""
    roots = [s for s in spans if not s.parent_span_id]
    ordered = sorted(roots or spans, key=lambda s: 0 if s.kind == "CHAIN" else 1)
    for span in ordered:
        attrs = span.attributes or {}
        if "input.value" in attrs or "output.value" in attrs:
            return attrs.get("input.value"), attrs.get("output.value")
    return None, None


def normalize_raw_spans(
    project_id: uuid.UUID,
    raw_spans: list[dict[str, Any]],
) -> list[Trace]:
    if not raw_spans:
        return []

    by_trace: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for raw_span in raw_spans:
        trace_id = raw_span.get("trace_id")
        if not trace_id:
            continue
        by_trace[str(trace_id)].append(raw_span)

    traces: list[Trace] = []
    for trace_id, spans_raw in by_trace.items():
        domain_spans: list[Span] = []
        for raw in spans_raw:
            attrs = dict(raw.get("attributes") or {})
            kind = resolve_span_kind(attrs)
            start = raw.get("start_time") or datetime.now(UTC)
            domain_spans.append(
                Span(
                    id=uuid.uuid4(),
                    span_id=str(raw["span_id"]),
                    parent_span_id=raw.get("parent_span_id"),
                    name=str(raw.get("name") or "span"),
                    kind=kind,
                    start_time=start,
                    end_time=raw.get("end_time"),
                    status=str(raw.get("status") or "unset"),
                    attributes=attrs,
                    events=list(raw.get("events") or []),
                )
            )

        start_time, end_time = _min_max_times(spans_raw)
        metadata: dict[str, Any] = {}
        for domain_span in domain_spans:
            metadata.update(extract_model_provider(domain_span.attributes))

        # Optional resource-ish fields from first span attributes
        first_attrs = spans_raw[0].get("attributes") or {}
        environment = first_attrs.get("deployment.environment") or first_attrs.get(
            "aiobs.environment"
        )
        user_id = first_attrs.get("user.id") or first_attrs.get("enduser.id")
        session_id = first_attrs.get("session.id")
        input_value, output_value = _extract_trace_io(domain_spans)

        traces.append(
            Trace(
                id=uuid.uuid4(),
                project_id=project_id,
                trace_id=trace_id,
                name=_pick_trace_name(spans_raw),
                status=_aggregate_status(spans_raw),
                start_time=start_time,
                end_time=end_time,
                input=input_value,
                output=output_value,
                metadata=metadata,
                environment=str(environment) if environment is not None else None,
                user_id=str(user_id) if user_id is not None else None,
                session_id=str(session_id) if session_id is not None else None,
                spans=tuple(domain_spans),
            )
        )
    return traces
