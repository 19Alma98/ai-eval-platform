"""Derive production live interactions from OTLP traces marked by the SDK.

``@opengrade.trace`` marks the outermost span of a production call with
``opengrade.live=true`` and ``opengrade.live.judge`` (the SDK-side sampling decision).
Ingestion turns that span into a ``LiveInteraction`` keyed by trace id, so
repeated or split OTLP batches never create duplicates.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass
from typing import Any

from opengrade_server.application.live_interactions import (
    SubmitLiveInteraction,
    SubmitLiveInteractionCommand,
)
from opengrade_server.domain.retrieval import normalize_documents
from opengrade_server.domain.trace import Span, Trace
from opengrade_server.evaluation.trace_context import build_eval_context_from_trace
from opengrade_server.tracing.run_binding import extract_run_binding

logger = logging.getLogger(__name__)

LIVE_ATTR = "opengrade.live"
LIVE_JUDGE_ATTR = "opengrade.live.judge"
LIVE_SAMPLE_RATE_ATTR = "opengrade.live.sample_rate"
EXTERNAL_ID_PREFIX = "trace:"

# kwargs names that most likely carry the user question / the answer.
_QUESTION_KEYS = ("question", "query", "input", "prompt", "message", "text")
_ANSWER_KEYS = ("answer", "output", "response", "content", "text")
# ``json.dumps(default=str)`` of a bound ``self`` / ``cls`` argument.
_OBJECT_REPR = re.compile(r"^<.+ (object|class) at 0x[0-9a-fA-F]+>$")

_warned_no_content = False


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def find_live_span(trace: Trace) -> Span | None:
    """Outermost span marked ``opengrade.live`` (the SDK marks only one per call)."""
    marked = [s for s in trace.spans if _truthy((s.attributes or {}).get(LIVE_ATTR, False))]
    if not marked:
        return None
    ids = {s.span_id for s in marked}
    outer = [s for s in marked if s.parent_span_id not in ids]
    return min(outer or marked, key=lambda s: s.start_time)


def _loads(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, ValueError):
        return value


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return text if text.strip() else None


def _pick_key(mapping: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def question_from_input(raw: Any) -> str | None:
    """Question text from ``input.value``.

    ``@opengrade.trace`` records ``{"args": [...], "kwargs": {...}}``: take a
    question-like kwarg, else the only string argument. ``opengrade.set_input()``
    with plain text always wins as-is.
    """
    parsed = _loads(raw)
    if isinstance(parsed, str):
        return _as_text(parsed)
    if isinstance(parsed, dict) and set(parsed) <= {"args", "kwargs"}:
        raw_args, raw_kwargs = parsed.get("args"), parsed.get("kwargs")
        args: list[Any] = raw_args if isinstance(raw_args, list) else []
        kwargs: dict[str, Any] = raw_kwargs if isinstance(raw_kwargs, dict) else {}
        picked = _pick_key(kwargs, _QUESTION_KEYS)
        if picked is not None:
            return picked
        strings = [
            v
            for v in [*args, *kwargs.values()]
            if isinstance(v, str) and v.strip() and not _OBJECT_REPR.match(v)
        ]
        if len(strings) == 1:
            return strings[0]
        if not args and not kwargs:
            return None
    return _as_text(raw)


def answer_from_output(raw: Any) -> str | None:
    parsed = _loads(raw)
    if isinstance(parsed, str):
        return _as_text(parsed)
    if isinstance(parsed, dict):
        picked = _pick_key(parsed, _ANSWER_KEYS)
        if picked is not None:
            return picked
    return _as_text(raw)


def _documents(trace: Trace, span: Span) -> list[dict[str, Any]]:
    docs = build_eval_context_from_trace(trace).get("documents")
    if docs:
        return list(docs)
    # opengrade.set_retrieval_documents() called directly inside the live span.
    return normalize_documents(_loads((span.attributes or {}).get("retrieval.documents")))


def live_command_from_trace(trace: Trace) -> SubmitLiveInteractionCommand | None:
    """Build the submit command for a live-marked trace, or None to skip it."""
    global _warned_no_content
    span = find_live_span(trace)
    if span is None or extract_run_binding(trace) is not None:
        return None
    attrs = span.attributes or {}
    if "input.value" not in attrs and "output.value" not in attrs:
        # Content was redacted at ingestion (CONTENT_CAPTURE_ENABLED off) or not captured.
        if not _warned_no_content:
            _warned_no_content = True
            logger.warning(
                "Live trace %s has no input/output; live interactions need "
                "CONTENT_CAPTURE_ENABLED=true and capture_input/capture_output on",
                trace.trace_id,
            )
        return None
    question = question_from_input(attrs.get("input.value"))
    answer = answer_from_output(attrs.get("output.value"))
    if question is None or answer is None:
        logger.debug("Live trace %s skipped: empty question or answer", trace.trace_id)
        return None

    metadata: dict[str, Any] = {
        **trace.metadata,
        "source_trace_id": trace.trace_id,
        "source_span_id": span.span_id,
    }
    rate = attrs.get(LIVE_SAMPLE_RATE_ATTR)
    if isinstance(rate, int | float) and not isinstance(rate, bool):
        metadata["live_sample_rate"] = float(rate)
    if trace.environment:
        metadata.setdefault("environment", trace.environment)
    if trace.session_id:
        metadata.setdefault("session_id", trace.session_id)
    if trace.user_id:
        metadata.setdefault("user_id", trace.user_id)

    return SubmitLiveInteractionCommand(
        project_id=trace.project_id,
        question=question,
        answer=answer,
        documents=_documents(trace, span),
        metadata=metadata,
        external_id=f"{EXTERNAL_ID_PREFIX}{trace.trace_id}",
        judge=_truthy(attrs.get(LIVE_JUDGE_ATTR, True)),
    )


def traces_for_live_binding(payload_traces: list[Trace], saved_traces: list[Trace]) -> list[Trace]:
    """Live-marked traces whose marked span arrived in this payload.

    Prefer the DB-merged trace (it may hold retrieval spans from an earlier
    batch); fall back to the payload when the merged copy lost the span.
    """
    saved_by_id = {trace.trace_id: trace for trace in saved_traces}
    chosen: list[Trace] = []
    for payload in payload_traces:
        if find_live_span(payload) is None:
            continue
        saved = saved_by_id.get(payload.trace_id)
        chosen.append(saved if saved is not None and find_live_span(saved) else payload)
    return chosen


@dataclass(frozen=True, slots=True)
class CreateLiveInteractionsFromTraces:
    submit: SubmitLiveInteraction

    async def execute(self, traces: list[Trace]) -> list[uuid.UUID]:
        """Create live interactions; return ids that still need the judge."""
        to_score: list[uuid.UUID] = []
        for trace in traces:
            command = live_command_from_trace(trace)
            if command is None:
                continue
            try:
                result = await self.submit.execute(command)
            except Exception:
                logger.warning(
                    "Live interaction from trace %s failed", trace.trace_id, exc_info=True
                )
                continue
            # Re-sent batches hit the existing row; only a fresh insert schedules the judge.
            if result.created and result.interaction.judge_status == "pending":
                to_score.append(result.interaction.id)
        return to_score
