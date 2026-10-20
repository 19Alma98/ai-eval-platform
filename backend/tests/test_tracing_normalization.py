from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from opengrade_server.domain.trace import Span, Trace
from opengrade_server.tracing.ingestion import ingest_otlp_payload
from opengrade_server.tracing.normalization import (
    batch_defines_trace_summary,
    normalize_raw_spans,
)
from opengrade_server.tracing.openinference import resolve_span_kind
from opengrade_server.tracing.redaction import redact_attributes, redact_trace


def test_resolve_span_kind_openinference() -> None:
    assert resolve_span_kind({"openinference.span.kind": "LLM"}) == "LLM"
    assert resolve_span_kind({"openinference.span.kind": "embedding"}) == "EMBEDDING"
    assert resolve_span_kind({}) == "SPAN"


def test_resolve_span_kind_genai_execute_tool() -> None:
    assert resolve_span_kind({"gen_ai.operation.name": "execute_tool"}) == "TOOL"


def test_normalize_llm_child_only_batch_does_not_promote_name_or_io() -> None:
    project_id = uuid.uuid4()
    start = datetime(2026, 1, 1, tzinfo=UTC)
    raw = [
        {
            "trace_id": "a" * 32,
            "span_id": "c" * 16,
            "parent_span_id": "b" * 16,
            "name": "ChatCompletion",
            "start_time": start,
            "end_time": start,
            "status": "ok",
            "attributes": {
                "openinference.span.kind": "LLM",
                "input.value": "system: you are a bot",
                "output.value": "completion text",
            },
            "events": [],
        },
    ]
    assert batch_defines_trace_summary(raw) is False
    traces = normalize_raw_spans(project_id, raw)
    assert len(traces) == 1
    assert traces[0].name == "trace"
    assert traces[0].input is None
    assert traces[0].output is None
    assert traces[0].spans[0].name == "ChatCompletion"


def test_normalize_groups_by_trace_id() -> None:
    project_id = uuid.uuid4()
    start = datetime(2026, 1, 1, tzinfo=UTC)
    raw = [
        {
            "trace_id": "a" * 32,
            "span_id": "b" * 16,
            "parent_span_id": None,
            "name": "chain",
            "start_time": start,
            "end_time": start,
            "status": "ok",
            "attributes": {
                "openinference.span.kind": "CHAIN",
                "input.value": "what is auth?",
                "output.value": "trusted network, no login",
            },
            "events": [],
        },
        {
            "trace_id": "a" * 32,
            "span_id": "c" * 16,
            "parent_span_id": "b" * 16,
            "name": "chat",
            "start_time": start,
            "end_time": start,
            "status": "ok",
            "attributes": {
                "openinference.span.kind": "LLM",
                "gen_ai.request.model": "gpt-4o-mini",
                "gen_ai.input.messages": [{"role": "user", "content": "secret"}],
            },
            "events": [],
        },
    ]
    traces = normalize_raw_spans(project_id, raw)
    assert len(traces) == 1
    assert traces[0].trace_id == "a" * 32
    assert traces[0].name == "chain"
    assert len(traces[0].spans) == 2
    assert traces[0].metadata.get("model") == "gpt-4o-mini"
    assert traces[0].input == "what is auth?"
    assert traces[0].output == "trusted network, no login"


def test_redaction_strips_content_when_disabled() -> None:
    project_id = uuid.uuid4()
    span = Span(
        id=uuid.uuid4(),
        span_id="1" * 16,
        parent_span_id=None,
        name="llm",
        kind="LLM",
        start_time=datetime.now(UTC),
        end_time=None,
        status="ok",
        attributes={
            "gen_ai.input.messages": [{"role": "user", "content": "secret"}],
            "gen_ai.request.model": "gpt-4o-mini",
            "gen_ai.usage.input_tokens": 10,
        },
    )
    trace = Trace(
        id=uuid.uuid4(),
        project_id=project_id,
        trace_id="a" * 32,
        name="t",
        status="ok",
        start_time=datetime.now(UTC),
        end_time=None,
        input={"prompt": "secret"},
        output={"text": "secret"},
        spans=(span,),
    )
    redacted = redact_trace(trace, content_capture_enabled=False)
    assert redacted.input is None
    assert redacted.output is None
    assert "gen_ai.input.messages" not in redacted.spans[0].attributes
    assert redacted.spans[0].attributes["gen_ai.request.model"] == "gpt-4o-mini"
    assert redacted.spans[0].attributes["gen_ai.usage.input_tokens"] == 10


def test_ingest_otlp_json_roundtrip() -> None:
    project_id = uuid.uuid4()
    payload = {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {
                            "key": "service.name",
                            "value": {"stringValue": "demo"},
                        }
                    ]
                },
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": "aa" * 16,
                                "spanId": "bb" * 8,
                                "name": "hello",
                                "startTimeUnixNano": "1700000000000000000",
                                "endTimeUnixNano": "1700000001000000000",
                                "status": {"code": "STATUS_CODE_OK"},
                                "attributes": [
                                    {
                                        "key": "openinference.span.kind",
                                        "value": {"stringValue": "CHAIN"},
                                    },
                                    {
                                        "key": "input.value",
                                        "value": {"stringValue": "secret"},
                                    },
                                ],
                            }
                        ]
                    }
                ],
            }
        ]
    }
    body = json.dumps(payload).encode("utf-8")
    traces = ingest_otlp_payload(
        project_id=project_id,
        body=body,
        content_type="application/json",
        content_capture_enabled=False,
    )
    assert len(traces) == 1
    assert traces[0].trace_id == "aa" * 16
    assert traces[0].spans[0].kind == "CHAIN"
    assert "input.value" not in traces[0].spans[0].attributes
    assert traces[0].spans[0].attributes.get("service.name") == "demo"


def test_ingest_otlp_non_finite_doubles_become_none() -> None:
    project_id = uuid.uuid4()
    # allow_nan so the body carries NaN/Inf tokens the way some OTLP JSON exporters do.
    body = json.dumps(
        {
            "resourceSpans": [
                {
                    "scopeSpans": [
                        {
                            "spans": [
                                {
                                    "traceId": "cc" * 16,
                                    "spanId": "dd" * 8,
                                    "name": "metrics",
                                    "startTimeUnixNano": "1700000000000000000",
                                    "endTimeUnixNano": "1700000001000000000",
                                    "attributes": [
                                        {
                                            "key": "score.nan",
                                            "value": {"doubleValue": float("nan")},
                                        },
                                        {
                                            "key": "score.inf",
                                            "value": {"doubleValue": float("inf")},
                                        },
                                        {
                                            "key": "score.ninf",
                                            "value": {"doubleValue": float("-inf")},
                                        },
                                        {
                                            "key": "score.ok",
                                            "value": {"doubleValue": 0.95},
                                        },
                                    ],
                                }
                            ]
                        }
                    ]
                }
            ]
        },
        allow_nan=True,
    ).encode("utf-8")

    traces = ingest_otlp_payload(
        project_id=project_id,
        body=body,
        content_type="application/json",
        content_capture_enabled=False,
    )
    attrs = traces[0].spans[0].attributes
    assert attrs["score.nan"] is None
    assert attrs["score.inf"] is None
    assert attrs["score.ninf"] is None
    assert attrs["score.ok"] == 0.95


def test_ingest_otlp_strips_nul_from_names_and_attrs() -> None:
    project_id = uuid.uuid4()
    payload = {
        "resourceSpans": [
            {
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": "ee" * 16,
                                "spanId": "ff" * 8,
                                "name": "hel\x00lo",
                                "startTimeUnixNano": "1700000000000000000",
                                "endTimeUnixNano": "1700000001000000000",
                                "attributes": [
                                    {
                                        "key": "openinference.span.kind",
                                        "value": {"stringValue": "CHAIN"},
                                    },
                                    {
                                        "key": "lab\x00el",
                                        "value": {"stringValue": "a\x00b"},
                                    },
                                ],
                                "events": [
                                    {
                                        "name": "ev\x00ent",
                                        "timeUnixNano": "1700000000500000000",
                                        "attributes": [
                                            {
                                                "key": "msg",
                                                "value": {"stringValue": "ok\x00"},
                                            }
                                        ],
                                    }
                                ],
                            }
                        ]
                    }
                ]
            }
        ]
    }
    body = json.dumps(payload).encode("utf-8")
    traces = ingest_otlp_payload(
        project_id=project_id,
        body=body,
        content_type="application/json",
        content_capture_enabled=False,
    )
    span = traces[0].spans[0]
    assert span.name == "hello"
    assert span.attributes["label"] == "ab"
    assert "lab\x00el" not in span.attributes
    assert span.events[0]["name"] == "event"
    assert span.events[0]["attributes"]["msg"] == "ok"


def test_redaction_drops_flattened_content_and_document_text() -> None:
    attrs = {
        "llm.model_name": "gpt",
        "llm.token_count.total": 12,
        "llm.input_messages.0.message.role": "user",
        "llm.input_messages.0.message.content": "SECRET prompt",
        "llm.output_messages.0.message.content": "SECRET answer",
        "llm.prompt_template.variables.question": "SECRET",
        "gen_ai.prompt.0.content": "SECRET",
        "embedding.embeddings.0.embedding.text": "SECRET",
        "retrieval.documents.0.document.id": "pto",
        "retrieval.documents.0.document.score": 0.9,
        "retrieval.documents.0.document.content": "SECRET doc",
        "reranker.output_documents.1.document.content": "SECRET doc",
        "retrieval.documents": json.dumps(
            [{"id": "pto", "title": "PTO", "text": "SECRET", "content": "SECRET", "score": 0.9}]
        ),
        "documents": [{"id": "vpn", "page_content": "SECRET"}],
        "reranker.input_documents": "not json SECRET",
    }
    redacted = redact_attributes(attrs, content_capture_enabled=False)

    assert "SECRET" not in json.dumps(redacted)
    assert redacted["llm.model_name"] == "gpt"
    assert redacted["llm.token_count.total"] == 12
    assert redacted["retrieval.documents.0.document.id"] == "pto"
    assert redacted["retrieval.documents.0.document.score"] == 0.9
    assert json.loads(redacted["retrieval.documents"]) == [
        {"id": "pto", "title": "PTO", "score": 0.9}
    ]
    assert redacted["documents"] == [{"id": "vpn"}]
    assert "reranker.input_documents" not in redacted
    # Capture on: untouched.
    assert redact_attributes(attrs, content_capture_enabled=True) == attrs
