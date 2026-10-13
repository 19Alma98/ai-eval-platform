from __future__ import annotations

import json
import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx2 import ASGITransport, AsyncClient

from aiobs_server.api.deps import (
    get_live_interaction_repository,
    get_metrics_set_repository,
    get_project_repository,
    get_trace_repository,
)
from aiobs_server.config import get_settings
from aiobs_server.domain.project import Project
from aiobs_server.domain.trace import Span, Trace
from aiobs_server.main import create_app
from aiobs_server.tracing.live_binding import (
    answer_from_output,
    find_live_span,
    live_command_from_trace,
    question_from_input,
)
from tests.support.repositories import InMemoryMetricsSetRepository
from tests.test_api_live_interactions import InMemoryLiveRepository, InMemoryProjectRepository
from tests.test_api_otlp import InMemoryTraceRepository

TRACE_ID = "ab" * 16
ROOT = "11" * 8
CHILD = "22" * 8


def _attr(key: str, value: Any) -> dict[str, Any]:
    if isinstance(value, bool):
        return {"key": key, "value": {"boolValue": value}}
    if isinstance(value, float):
        return {"key": key, "value": {"doubleValue": value}}
    return {"key": key, "value": {"stringValue": value}}


def _payload(
    *,
    trace_id: str = TRACE_ID,
    judge: bool = True,
    extra_root_attrs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    docs = json.dumps([{"id": "doc-1", "title": "Policy", "text": "Remote OK."}])
    root_attrs = [
        _attr("openinference.span.kind", "CHAIN"),
        _attr("input.value", json.dumps({"args": ["Can I work remotely?"], "kwargs": {}})),
        _attr("output.value", "Yes, remote work is allowed."),
        _attr("aiobs.live", True),
        _attr("aiobs.live.judge", judge),
        _attr("aiobs.live.sample_rate", 0.5),
        *(extra_root_attrs or []),
    ]
    return {
        "resourceSpans": [
            {
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": trace_id,
                                "spanId": ROOT,
                                "name": "answer",
                                "startTimeUnixNano": "1700000000000000000",
                                "endTimeUnixNano": "1700000001000000000",
                                "status": {"code": "STATUS_CODE_OK"},
                                "attributes": root_attrs,
                            },
                            {
                                "traceId": trace_id,
                                "spanId": CHILD,
                                "parentSpanId": ROOT,
                                "name": "retrieve",
                                "startTimeUnixNano": "1700000000000000000",
                                "endTimeUnixNano": "1700000000500000000",
                                "status": {"code": "STATUS_CODE_OK"},
                                "attributes": [
                                    _attr("openinference.span.kind", "RETRIEVER"),
                                    _attr("retrieval.documents", docs),
                                ],
                            },
                        ]
                    }
                ]
            }
        ]
    }


class _Env:
    def __init__(self) -> None:
        self.projects = InMemoryProjectRepository()
        self.live = InMemoryLiveRepository()


@pytest.fixture
async def env() -> AsyncIterator[tuple[AsyncClient, _Env, str]]:
    os.environ["CONTENT_CAPTURE_ENABLED"] = "true"
    get_settings.cache_clear()
    state = _Env()
    project = await state.projects.add(Project.create("Live OTLP", slug="live-otlp"))

    app = create_app()
    traces = InMemoryTraceRepository()
    metrics_sets = InMemoryMetricsSetRepository()
    app.dependency_overrides[get_project_repository] = lambda: state.projects
    app.dependency_overrides[get_trace_repository] = lambda: traces
    app.dependency_overrides[get_live_interaction_repository] = lambda: state.live
    app.dependency_overrides[get_metrics_set_repository] = lambda: metrics_sets

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, state, str(project.id)

    app.dependency_overrides.clear()
    os.environ.pop("CONTENT_CAPTURE_ENABLED", None)
    get_settings.cache_clear()


async def _post(client: AsyncClient, project_id: str, payload: dict[str, Any]) -> None:
    res = await client.post(
        "/v1/traces",
        content=json.dumps(payload),
        headers={"content-type": "application/json", "X-Project-Id": project_id},
    )
    assert res.status_code == 200, res.text


@pytest.mark.asyncio
async def test_live_trace_creates_interaction(env: tuple[AsyncClient, _Env, str]) -> None:
    client, state, project_id = env
    await _post(client, project_id, _payload())

    items = list(state.live._items.values())
    assert len(items) == 1
    item = items[0]
    assert item.question == "Can I work remotely?"
    assert item.answer == "Yes, remote work is allowed."
    assert item.external_id == f"trace:{TRACE_ID}"
    assert item.documents[0]["id"] == "doc-1"
    assert item.metadata["source_trace_id"] == TRACE_ID
    assert item.metadata["source_span_id"] == ROOT
    assert item.metadata["live_sample_rate"] == 0.5
    assert item.judge_status == "pending"


@pytest.mark.asyncio
async def test_unsampled_trace_is_stored_without_judge(
    env: tuple[AsyncClient, _Env, str],
) -> None:
    client, state, project_id = env
    await _post(client, project_id, _payload(judge=False))

    (item,) = state.live._items.values()
    assert item.judge_status == "unsampled"


@pytest.mark.asyncio
async def test_resent_batch_does_not_duplicate(env: tuple[AsyncClient, _Env, str]) -> None:
    client, state, project_id = env
    await _post(client, project_id, _payload())
    await _post(client, project_id, _payload())
    assert len(state.live._items) == 1


@pytest.mark.asyncio
async def test_experiment_bound_trace_is_not_live(env: tuple[AsyncClient, _Env, str]) -> None:
    client, state, project_id = env
    payload = _payload(
        extra_root_attrs=[
            _attr("aiobs.experiment_id", "00000000-0000-0000-0000-000000000001"),
            _attr("aiobs.dataset_item_id", "00000000-0000-0000-0000-000000000002"),
        ]
    )
    await _post(client, project_id, payload)
    assert state.live._items == {}


@pytest.mark.asyncio
async def test_redacted_content_skips_live(env: tuple[AsyncClient, _Env, str]) -> None:
    client, state, project_id = env
    os.environ["CONTENT_CAPTURE_ENABLED"] = "false"
    get_settings.cache_clear()
    await _post(client, project_id, _payload())
    assert state.live._items == {}
    # The trace itself is still ingested.
    detail = await client.get(f"/api/v1/projects/{project_id}/traces/{TRACE_ID}")
    assert detail.status_code == 200


def _span(span_id: str, parent: str | None, attrs: dict[str, Any]) -> Span:
    now = datetime(2024, 1, 1, tzinfo=UTC)
    return Span(
        id=uuid.uuid4(),
        span_id=span_id,
        parent_span_id=parent,
        name=span_id,
        kind="CHAIN",
        start_time=now,
        end_time=now,
        status="ok",
        attributes=attrs,
    )


def _trace(*spans: Span) -> Trace:
    now = datetime(2024, 1, 1, tzinfo=UTC)
    return Trace(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        trace_id=TRACE_ID,
        name="t",
        status="ok",
        start_time=now,
        end_time=now,
        spans=spans,
    )


def test_question_from_input_variants() -> None:
    args = json.dumps({"args": ["<app.Bot object at 0x7f00ab>", "hello?"], "kwargs": {}})
    assert question_from_input(args) == "hello?"
    kw = json.dumps({"args": [], "kwargs": {"query": "q1", "user": "u"}})
    assert question_from_input(kw) == "q1"
    assert question_from_input("plain question") == "plain question"
    ambiguous = json.dumps({"args": ["a", "b"], "kwargs": {}})
    assert question_from_input(ambiguous) == ambiguous
    assert question_from_input(json.dumps({"args": [], "kwargs": {}})) is None
    assert question_from_input("   ") is None


def test_answer_from_output_variants() -> None:
    assert answer_from_output("plain") == "plain"
    assert answer_from_output(json.dumps("quoted")) == "quoted"
    assert answer_from_output(json.dumps({"answer": "a", "sources": []})) == "a"
    assert answer_from_output(json.dumps([1, 2])) == "[1, 2]"
    assert answer_from_output(None) is None


def test_find_live_span_picks_outermost() -> None:
    outer = _span("outer", None, {"aiobs.live": True})
    inner = _span("inner", "outer", {"aiobs.live": True})
    plain = _span("plain", None, {})
    assert find_live_span(_trace(inner, outer, plain)) is outer
    assert find_live_span(_trace(plain)) is None


def test_live_command_uses_documents_set_on_live_span() -> None:
    docs = json.dumps([{"id": "d1", "text": "t"}])
    span = _span(
        "root",
        None,
        {
            "aiobs.live": True,
            "aiobs.live.judge": False,
            "input.value": "q",
            "output.value": "a",
            "retrieval.documents": docs,
        },
    )
    command = live_command_from_trace(_trace(span))
    assert command is not None
    assert command.documents == [{"id": "d1", "text": "t"}]
    assert command.judge is False
