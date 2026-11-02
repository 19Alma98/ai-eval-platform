"""Normalize raw OTLP spans into domain Trace trees."""

from __future__ import annotations

import json
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from opengrade_server.domain.trace import (
    MAX_ATTRIBUTE_VALUE_CHARS,
    MAX_METADATA_KEYS,
    MAX_TAG_CHARS,
    MAX_TRACE_TAGS,
    Span,
    Trace,
)
from opengrade_server.tracing.openinference import extract_model_provider, resolve_span_kind


def batch_defines_trace_summary(spans: list[Span] | list[dict[str, Any]]) -> bool:
    """True when this batch may set trace-level name / input / output.

    Child-only LLM/TOOL batches must not promote span I/O to the trace row.
    A root span or any CHAIN span is enough to define the summary.
    """
    for span in spans:
        if isinstance(span, Span):
            if not span.parent_span_id or span.kind.upper() == "CHAIN":
                return True
            continue
        if not span.get("parent_span_id"):
            return True
        kind = resolve_span_kind(span.get("attributes") or {})
        if kind == "CHAIN":
            return True
    return False


def _pick_trace_name(spans: list[dict[str, Any]]) -> str:
    if not batch_defines_trace_summary(spans):
        return "trace"
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
    if not batch_defines_trace_summary(spans):
        return None, None
    roots = [s for s in spans if not s.parent_span_id]
    ordered = sorted(roots or spans, key=lambda s: 0 if s.kind == "CHAIN" else 1)
    for span in ordered:
        attrs = span.attributes or {}
        if "input.value" in attrs or "output.value" in attrs:
            return attrs.get("input.value"), attrs.get("output.value")
    return None, None


def _roots_first(spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(spans, key=lambda s: 0 if not s.get("parent_span_id") else 1)


def _first_attr(spans: list[dict[str, Any]], *keys: str) -> Any | None:
    """First non-empty value of ``keys`` across spans, root spans first."""
    for span in _roots_first(spans):
        attrs = span.get("attributes") or {}
        for key in keys:
            value = attrs.get(key)
            if value is not None and value != "":
                return value
    return None


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list | tuple):
        return list(value)
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("["):
            try:
                parsed = json.loads(text)
            except ValueError:
                return [text]
            return parsed if isinstance(parsed, list) else [text]
        return [text]
    return [value]


def extract_tags(spans: list[dict[str, Any]]) -> tuple[str, ...]:
    """OpenInference ``tag.tags`` from every span, root first, deduplicated."""
    tags: list[str] = []
    for span in _roots_first(spans):
        for raw in _as_list((span.get("attributes") or {}).get("tag.tags")):
            if raw is None:
                continue
            tag = str(raw).strip()[:MAX_TAG_CHARS]
            if tag and tag not in tags:
                tags.append(tag)
    return tuple(tags[:MAX_TRACE_TAGS])


def extract_user_metadata(spans: list[dict[str, Any]]) -> dict[str, Any]:
    """OpenInference ``metadata`` (a JSON object string) merged across spans; root wins."""
    merged: dict[str, Any] = {}
    # Children first so the root span's values override nested ones.
    for span in reversed(_roots_first(spans)):
        raw = (span.get("attributes") or {}).get("metadata")
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except ValueError:
                continue
        if not isinstance(raw, dict):
            continue
        for key, value in raw.items():
            name = str(key).strip()
            if not name or name.startswith("_"):
                continue  # ``_``-prefixed keys are reserved for the platform
            if value is not None and not isinstance(value, bool | int | float | str):
                value = json.dumps(value, default=str)
            if isinstance(value, str):
                value = value[:MAX_ATTRIBUTE_VALUE_CHARS]
            merged[name[:MAX_TAG_CHARS]] = value
    return dict(list(merged.items())[:MAX_METADATA_KEYS])


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
        metadata.update(extract_user_metadata(spans_raw))

        first_attrs = spans_raw[0].get("attributes") or {}
        environment = (
            first_attrs.get("deployment.environment")
            or first_attrs.get("deployment.environment.name")
            or first_attrs.get("opengrade.environment")
        )
        version = first_attrs.get("service.version") or first_attrs.get("opengrade.version")
        # Set by opengrade.set_user / set_session (or OpenInference using_attributes) on
        # any span of the trace: the root span wins.
        user_id = _first_attr(spans_raw, "user.id", "enduser.id")
        session_id = _first_attr(spans_raw, "session.id", "gen_ai.conversation.id")
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
                user_id=str(user_id)[:200] if user_id is not None else None,
                session_id=str(session_id)[:200] if session_id is not None else None,
                spans=tuple(domain_spans),
                version=str(version)[:200] if version is not None else None,
                tags=extract_tags(spans_raw),
            )
        )
    return traces
