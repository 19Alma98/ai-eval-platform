"""Content capture / attribute redaction."""

from __future__ import annotations

import json
import re
from typing import Any

from opengrade_server.domain.trace import Span, Trace
from opengrade_server.tracing.openinference import CONTENT_ATTRIBUTE_KEYS

# Retrieved documents: with capture off their text is dropped but ids, titles, scores
# and metadata stay, so retrieval metrics (hit@k, recall, MRR) still work.
DOCUMENT_ATTRIBUTE_KEYS = (
    "retrieval.documents",
    "reranker.input_documents",
    "reranker.output_documents",
    "documents",
)
_DOCUMENT_TEXT_FIELDS = frozenset({"text", "content", "page_content"})
_FLAT_DOCUMENT_TEXT = re.compile(r"^\d+\.document\.content$")
_FLAT_EMBEDDING_TEXT = re.compile(r"^embedding\.embeddings\.\d+\.embedding\.text$")


def _is_content_key(key: str) -> bool:
    """Text-bearing key, including OpenInference / GenAI flattened forms
    (``llm.input_messages.0.message.content``, ``gen_ai.prompt.0.content``)."""
    if key in CONTENT_ATTRIBUTE_KEYS or _FLAT_EMBEDDING_TEXT.match(key):
        return True
    if any(key.startswith(f"{base}.") for base in CONTENT_ATTRIBUTE_KEYS):
        return True
    for base in DOCUMENT_ATTRIBUTE_KEYS:
        if key.startswith(f"{base}.") and _FLAT_DOCUMENT_TEXT.match(key[len(base) + 1 :]):
            return True
    return False


def _strip_document_text(value: Any) -> Any:
    """Aggregated document list (JSON string or list) without the text fields."""
    parsed = value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None  # unparseable: may be raw text, drop it
    if not isinstance(parsed, list):
        return None
    stripped = [
        {k: v for k, v in doc.items() if k not in _DOCUMENT_TEXT_FIELDS}
        for doc in parsed
        if isinstance(doc, dict)
    ]
    return json.dumps(stripped) if isinstance(value, str) else stripped


def redact_attributes(
    attributes: dict[str, Any], *, content_capture_enabled: bool
) -> dict[str, Any]:
    if content_capture_enabled:
        return dict(attributes)
    out: dict[str, Any] = {}
    for key, value in attributes.items():
        if _is_content_key(key):
            continue
        if key in DOCUMENT_ATTRIBUTE_KEYS:
            value = _strip_document_text(value)
            if value is None:
                continue
        out[key] = value
    return out


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
        version=trace.version,
        user_id=trace.user_id,
        session_id=trace.session_id,
        spans=spans,
    )
