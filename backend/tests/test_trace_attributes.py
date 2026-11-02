"""Trace user / session / tags / metadata: extraction at ingestion and list filters."""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx2 import ASGITransport, AsyncClient

from opengrade_server.config import get_settings
from opengrade_server.domain.trace import Trace, trace_attribute_pairs
from opengrade_server.infrastructure.db import bootstrap_schema, dispose_db, init_db
from opengrade_server.main import create_app
from opengrade_server.tracing.normalization import (
    extract_tags,
    extract_user_metadata,
    normalize_raw_spans,
)

_START = datetime(2026, 1, 1, tzinfo=UTC)


def _raw(span_id: str, parent: str | None, attrs: dict[str, Any]) -> dict[str, Any]:
    return {
        "trace_id": "a" * 32,
        "span_id": span_id,
        "parent_span_id": parent,
        "name": f"span-{span_id[:2]}",
        "start_time": _START,
        "end_time": _START,
        "status": "ok",
        "attributes": attrs,
        "events": [],
    }


def test_user_and_session_come_from_any_span_root_first() -> None:
    raw = [
        _raw("c" * 16, "b" * 16, {"user.id": "child-user", "session.id": "chat-1"}),
        _raw("b" * 16, None, {"user.id": "root-user"}),
    ]
    trace = normalize_raw_spans(uuid.uuid4(), raw)[0]
    assert trace.user_id == "root-user"
    assert trace.session_id == "chat-1"


def test_tags_union_across_spans_and_formats() -> None:
    raw = [
        _raw("b" * 16, None, {"tag.tags": ["beta", "eu"]}),
        _raw("c" * 16, "b" * 16, {"tag.tags": '["eu", "rerank-v2"]'}),
        _raw("d" * 16, "b" * 16, {"tag.tags": "single"}),
    ]
    assert extract_tags(raw) == ("beta", "eu", "rerank-v2", "single")


def test_metadata_merged_root_wins_and_reserved_keys_dropped() -> None:
    raw = [
        _raw("c" * 16, "b" * 16, {"metadata": json.dumps({"tenant": "child", "n": 1})}),
        _raw(
            "b" * 16,
            None,
            {"metadata": json.dumps({"tenant": "acme", "_span_count": 99, "cfg": {"k": 5}})},
        ),
        _raw("d" * 16, "b" * 16, {"metadata": "not json"}),
    ]
    meta = extract_user_metadata(raw)
    assert meta == {"tenant": "acme", "n": 1, "cfg": '{"k": 5}'}
    trace = normalize_raw_spans(uuid.uuid4(), raw)[0]
    assert trace.metadata["tenant"] == "acme"
    assert "_span_count" not in trace.metadata


def test_attribute_pairs_index_tags_and_scalar_metadata() -> None:
    trace = Trace(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        trace_id="a" * 32,
        name="t",
        status="ok",
        start_time=_START,
        end_time=None,
        metadata={"tenant": "acme", "beta": True, "n": 3, "_internal": "x", "nested": {"a": 1}},
        tags=("beta",),
    )
    assert trace_attribute_pairs(trace) == {
        ("tag", "beta"),
        ("metadata.tenant", "acme"),
        ("metadata.beta", "true"),
        ("metadata.n", "3"),
    }


# --- end to end on SQLite -------------------------------------------------------------


@pytest.fixture
async def client(tmp_path_factory: pytest.TempPathFactory) -> AsyncIterator[AsyncClient]:
    db_path = tmp_path_factory.mktemp("sqlite") / "opengrade.db"
    previous_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"
    get_settings.cache_clear()
    await dispose_db()
    init_db(get_settings())
    await bootstrap_schema()
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await dispose_db()
    if previous_url is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = previous_url
    get_settings.cache_clear()


def _attr(key: str, value: Any) -> dict[str, Any]:
    if isinstance(value, list):
        return {
            "key": key,
            "value": {"arrayValue": {"values": [{"stringValue": v} for v in value]}},
        }
    return {"key": key, "value": {"stringValue": value}}


def _otlp(trace_id: str, span_id: str, parent: str | None, attrs: list[dict[str, Any]]) -> dict:
    span: dict[str, Any] = {
        "traceId": trace_id,
        "spanId": span_id,
        "name": "answer",
        "startTimeUnixNano": "1700000000000000000",
        "endTimeUnixNano": "1700000001000000000",
        "status": {"code": "STATUS_CODE_OK"},
        "attributes": [_attr("openinference.span.kind", "CHAIN"), *attrs],
    }
    if parent:
        span["parentSpanId"] = parent
    return {"resourceSpans": [{"scopeSpans": [{"spans": [span]}]}]}


async def _ingest(client: AsyncClient, slug: str, payload: dict) -> None:
    response = await client.post("/v1/traces", json=payload, headers={"X-Project-Slug": slug})
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_filter_traces_by_user_session_tags_and_metadata(client: AsyncClient) -> None:
    project = (
        await client.post("/api/v1/projects", json={"name": "Attrs", "slug": "attrs"})
    ).json()
    base = f"/api/v1/projects/{project['id']}/traces"
    t1, t2 = "1" * 32, "2" * 32

    await _ingest(
        client,
        "attrs",
        _otlp(
            t1,
            "a" * 16,
            None,
            [
                _attr("user.id", "u1"),
                _attr("session.id", "chat-1"),
                _attr("tag.tags", ["beta", "eu"]),
                _attr("metadata", json.dumps({"tenant": "acme", "tier": "gold"})),
            ],
        ),
    )
    # A later batch (child span) of the same trace adds a tag and a metadata key.
    await _ingest(
        client,
        "attrs",
        _otlp(
            t1,
            "b" * 16,
            "a" * 16,
            [_attr("tag.tags", ["rerank-v2"]), _attr("metadata", json.dumps({"k": 5}))],
        ),
    )
    await _ingest(
        client,
        "attrs",
        _otlp(
            t2,
            "c" * 16,
            None,
            [
                _attr("user.id", "u2"),
                _attr("tag.tags", ["eu"]),
                _attr("metadata", json.dumps({"tenant": "globex"})),
            ],
        ),
    )

    async def ids(**params: Any) -> list[str]:
        response = await client.get(base, params=params)
        assert response.status_code == 200, response.text
        return sorted(item["trace_id"] for item in response.json()["items"])

    assert await ids() == [t1, t2]
    assert await ids(tag="eu") == [t1, t2]
    assert await ids(tag=["eu", "beta"]) == [t1]
    assert await ids(tag="rerank-v2") == [t1]
    assert await ids(tag="missing") == []
    assert await ids(metadata="tenant:globex") == [t2]
    assert await ids(metadata=["tenant:acme", "k:5"]) == [t1]
    assert await ids(user_id="u2") == [t2]
    assert await ids(session_id="chat-1") == [t1]
    assert await ids(search="glob") == [t2]  # metadata values are searchable
    assert await ids(search="rerank") == [t1]  # and tags

    detail = (await client.get(f"{base}/{t1}")).json()
    assert detail["tags"] == ["beta", "eu", "rerank-v2"]
    assert detail["user_id"] == "u1"
    assert detail["metadata"]["tenant"] == "acme"
    assert detail["metadata"]["k"] == 5

    listed = (await client.get(base, params={"tag": "beta"})).json()["items"][0]
    assert listed["tags"] == ["beta", "eu", "rerank-v2"]

    bad = await client.get(base, params={"metadata": "no-colon"})
    assert bad.status_code == 422

    facets = (await client.get(f"{base}/facets")).json()
    assert facets["tags"][0] == {"value": "eu", "count": 2}
    assert {f["value"] for f in facets["metadata_keys"]} == {"tenant", "tier", "k"}
    assert {f["value"] for f in facets["users"]} == {"u1", "u2"}
    assert facets["sessions"] == [{"value": "chat-1", "count": 1}]


@pytest.mark.asyncio
async def test_facets_unknown_project_is_404(client: AsyncClient) -> None:
    response = await client.get(f"/api/v1/projects/{uuid.uuid4()}/traces/facets")
    assert response.status_code == 404
