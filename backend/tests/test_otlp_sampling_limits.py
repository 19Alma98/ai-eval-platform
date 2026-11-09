"""OTLP head sampling and span attribute size limits."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest
from httpx2 import ASGITransport, AsyncClient

from opengrade_server.api.deps import (
    get_app_settings,
    get_live_interaction_repository,
    get_project_repository,
    get_trace_repository,
    get_trace_score_repository,
)
from opengrade_server.config import Settings
from opengrade_server.domain.project import Project
from opengrade_server.domain.trace import Span, Trace
from opengrade_server.main import create_app
from opengrade_server.tracing.ingestion import ingest_otlp_payload
from opengrade_server.tracing.limits import apply_span_attr_limits, truncate_value
from opengrade_server.tracing.sampling import should_sample_trace_id
from tests.support.repositories import InMemoryTraceScoreRepository
from tests.test_api_live_interactions import InMemoryLiveRepository
from tests.test_api_otlp import (
    InMemoryProjectRepository,
    InMemoryTraceRepository,
    _minimal_otlp_payload,
)


def test_should_sample_rate_extremes() -> None:
    tid = "aa" * 16
    assert should_sample_trace_id(tid, 1.0) is True
    assert should_sample_trace_id(tid, 1.5) is True
    assert should_sample_trace_id(tid, 0.0) is False
    assert should_sample_trace_id(tid, -0.1) is False


def test_should_sample_rate_half_is_deterministic() -> None:
    # Low 64 bits of 0x00..00 are 0 → always under any positive bound.
    assert should_sample_trace_id("00" * 16, 0.5) is True
    # Low 64 bits all ones → never under a 0.5 bound (round(0.5 * 2^64) == 2^63).
    assert should_sample_trace_id("ff" * 16, 0.5) is False
    # Hex string and int agree.
    assert should_sample_trace_id(0, 0.5) is True
    assert should_sample_trace_id((1 << 64) - 1, 0.5) is False
    assert should_sample_trace_id("0x" + "ff" * 16, 0.5) is False


def test_should_sample_matches_sdk_should_judge() -> None:
    from opengrade._live import should_judge

    for tid in (0, 1, (1 << 63) - 1, (1 << 63), (1 << 64) - 1):
        for rate in (0.0, 0.1, 0.5, 0.9, 1.0):
            assert should_sample_trace_id(tid, rate) is should_judge(tid, rate)


def test_truncate_value_strings_and_nested() -> None:
    assert truncate_value("short", 10) == "short"
    assert truncate_value("abcdefghij", 5) == "abcde"
    assert truncate_value({"a": "abcdefghij", "n": 1}, 5) == {"a": "abcde", "n": 1}
    assert truncate_value(["abcdefghij", {"k": "zzzzzz"}], 3) == ["abc", {"k": "zzz"}]


def test_apply_span_attr_limits_truncates_attrs_events_io() -> None:
    now = datetime.now(UTC)
    span = Span(
        id=uuid.uuid4(),
        span_id="bb" * 8,
        parent_span_id=None,
        name="chain",
        kind="CHAIN",
        start_time=now,
        end_time=now,
        status="ok",
        attributes={"input.value": "x" * 100, "count": 3},
        events=[{"name": "e", "attributes": {"msg": "y" * 50}}],
    )
    trace = Trace(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        trace_id="aa" * 16,
        name="chain",
        status="ok",
        start_time=now,
        end_time=now,
        input="i" * 80,
        output="o" * 80,
        spans=(span,),
    )
    limited = apply_span_attr_limits(trace, 10)
    assert limited.spans[0].attributes["input.value"] == "x" * 10
    assert limited.spans[0].attributes["count"] == 3
    assert limited.spans[0].events[0]["attributes"]["msg"] == "y" * 10
    assert limited.input == "i" * 10
    assert limited.output == "o" * 10


def _otlp_body(trace_id: str, *, attr: str | None = None) -> bytes:
    attrs = [
        {"key": "openinference.span.kind", "value": {"stringValue": "CHAIN"}},
    ]
    if attr is not None:
        attrs.append({"key": "input.value", "value": {"stringValue": attr}})
    payload = {
        "resourceSpans": [
            {
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": trace_id,
                                "spanId": "bb" * 8,
                                "name": "chain",
                                "startTimeUnixNano": "1700000000000000000",
                                "endTimeUnixNano": "1700000001000000000",
                                "status": {"code": "STATUS_CODE_OK"},
                                "attributes": attrs,
                            }
                        ]
                    }
                ]
            }
        ]
    }
    return json.dumps(payload).encode("utf-8")


def test_ingest_sample_rate_zero_drops_all() -> None:
    traces = ingest_otlp_payload(
        project_id=uuid.uuid4(),
        body=_otlp_body("aa" * 16),
        content_type="application/json",
        content_capture_enabled=True,
        sample_rate=0.0,
    )
    assert traces == []


def test_ingest_sample_rate_one_keeps_all() -> None:
    traces = ingest_otlp_payload(
        project_id=uuid.uuid4(),
        body=_otlp_body("aa" * 16),
        content_type="application/json",
        content_capture_enabled=True,
        sample_rate=1.0,
    )
    assert len(traces) == 1


def test_ingest_sample_rate_half_is_deterministic() -> None:
    project_id = uuid.uuid4()
    kept = ingest_otlp_payload(
        project_id=project_id,
        body=_otlp_body("00" * 16),
        content_type="application/json",
        sample_rate=0.5,
    )
    dropped = ingest_otlp_payload(
        project_id=project_id,
        body=_otlp_body("ff" * 16),
        content_type="application/json",
        sample_rate=0.5,
    )
    assert len(kept) == 1
    assert dropped == []


def test_ingest_truncates_attributes() -> None:
    traces = ingest_otlp_payload(
        project_id=uuid.uuid4(),
        body=_otlp_body("aa" * 16, attr="z" * 100),
        content_type="application/json",
        content_capture_enabled=True,
        max_span_attr_chars=20,
    )
    assert traces[0].spans[0].attributes["input.value"] == "z" * 20


@pytest.mark.asyncio
async def test_otlp_returns_200_when_all_traces_dropped() -> None:
    projects = InMemoryProjectRepository()
    project = Project.create("Demo", "demo")
    await projects.add(project)
    traces_repo = InMemoryTraceRepository()
    app = create_app()
    app.dependency_overrides[get_project_repository] = lambda: projects
    app.dependency_overrides[get_trace_repository] = lambda: traces_repo
    app.dependency_overrides[get_trace_score_repository] = lambda: InMemoryTraceScoreRepository()
    app.dependency_overrides[get_live_interaction_repository] = lambda: InMemoryLiveRepository()
    app.dependency_overrides[get_app_settings] = lambda: Settings(otlp_trace_sample_rate=0.0)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        otlp = await ac.post(
            "/v1/traces",
            content=json.dumps(_minimal_otlp_payload()),
            headers={
                "content-type": "application/json",
                "X-Project-Id": str(project.id),
            },
        )
    assert otlp.status_code == 200
    assert traces_repo._traces == {}
    app.dependency_overrides.clear()
