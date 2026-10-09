from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from aiobs_server.domain.retrieval import normalize_documents
from aiobs_server.domain.trace import Span, Trace


def _attr_number(attributes: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = attributes.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def build_eval_context_from_trace(
    trace: Trace, *, source_span_id: str | None = None
) -> dict[str, Any]:
    """Derive evaluator context (latency, tokens, cost, tools) from a trace."""
    spans = list(trace.spans)
    if source_span_id:
        spans = [s for s in spans if s.span_id == source_span_id] or spans

    latency_ms = _trace_latency_ms(trace)
    total_tokens = 0.0
    prompt_tokens = 0.0
    completion_tokens = 0.0
    cost_usd = 0.0
    tool_calls: list[dict[str, Any]] = []
    has_tokens = False
    has_cost = False

    for span in spans:
        attrs = span.attributes or {}
        pt = _attr_number(
            attrs,
            "gen_ai.usage.input_tokens",
            "llm.token_count.prompt",
            "gen_ai.usage.prompt_tokens",
        )
        ct = _attr_number(
            attrs,
            "gen_ai.usage.output_tokens",
            "llm.token_count.completion",
            "gen_ai.usage.completion_tokens",
        )
        tt = _attr_number(
            attrs,
            "gen_ai.usage.total_tokens",
            "llm.token_count.total",
        )
        if pt is not None:
            prompt_tokens += pt
            has_tokens = True
        if ct is not None:
            completion_tokens += ct
            has_tokens = True
        if tt is not None:
            total_tokens += tt
            has_tokens = True
        elif pt is not None or ct is not None:
            total_tokens += (pt or 0.0) + (ct or 0.0)

        cost = _attr_number(attrs, "gen_ai.usage.cost", "llm.cost")
        if cost is not None:
            cost_usd += cost
            has_cost = True

        if span.kind.upper() == "TOOL":
            tool_calls.append(_tool_call_from_span(span))

    context: dict[str, Any] = {}
    if latency_ms is not None:
        context["latency_ms"] = latency_ms
    if has_tokens:
        context["total_tokens"] = total_tokens
        context["prompt_tokens"] = prompt_tokens
        context["completion_tokens"] = completion_tokens
    if has_cost:
        context["cost_usd"] = cost_usd
    if tool_calls:
        context["tool_calls"] = tool_calls

    # Use the final retrieval stage (e.g. reranker after retriever): those are the
    # documents the model actually saw, so hit@k ranks against them. Stages that did
    # not record documents are skipped; if none did, documents is an empty list.
    stages = [s for s in spans if s.kind.upper() in _RETRIEVAL_KINDS]
    if stages:
        recorded = [
            (_span_end(span), idx, docs)
            for idx, span in enumerate(stages)
            if (docs := _span_documents(span)) is not None
        ]
        final_docs = max(recorded, key=lambda row: (row[0], row[1]))[2] if recorded else []
        context["documents"] = _dedupe_by_id(final_docs)

    return context


_RETRIEVAL_KINDS = frozenset({"RETRIEVER", "RERANKER"})
_DOCUMENT_KEYS = {
    "RETRIEVER": ("retrieval.documents", "documents"),
    "RERANKER": ("reranker.output_documents", "retrieval.documents", "documents"),
}


def _span_end(span: Span) -> datetime:
    stamp = span.end_time or span.start_time
    return stamp if stamp.tzinfo is not None else stamp.replace(tzinfo=UTC)


def _span_documents(span: Span) -> list[dict[str, Any]] | None:
    """Documents recorded on a retrieval span, or None if it recorded none."""
    attrs = span.attributes or {}
    for key in _DOCUMENT_KEYS[span.kind.upper()]:
        raw = attrs.get(key)
        if raw is None:
            continue
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                return []
        return normalize_documents(raw)
    return None


def _dedupe_by_id(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for doc in docs:
        if doc["id"] in seen:
            continue
        seen.add(doc["id"])
        out.append(doc)
    return out


def _trace_latency_ms(trace: Trace) -> float | None:
    if trace.end_time is None:
        return None
    delta = trace.end_time - trace.start_time
    return delta.total_seconds() * 1000.0


def _tool_call_from_span(span: Span) -> dict[str, Any]:
    status = (span.status or "").lower()
    success = status in {"ok", "unset", ""}
    if status in {"error", "failed"}:
        success = False
    return {
        "name": span.name,
        "span_id": span.span_id,
        "success": success,
        "status": span.status,
    }
