from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from aiobs.domain.trace import Span, Trace
from aiobs.tracing.ingestion import ingest_otlp_payload
from aiobs.tracing.normalization import normalize_raw_spans
from aiobs.tracing.openinference import resolve_span_kind
from aiobs.tracing.redaction import redact_trace


def test_resolve_span_kind_openinference() -> None:
    assert resolve_span_kind({"openinference.span.kind": "LLM"}) == "LLM"
    assert resolve_span_kind({"openinference.span.kind": "embedding"}) == "EMBEDDING"
    assert resolve_span_kind({}) == "SPAN"


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
