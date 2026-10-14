"""SQLite local-mode smoke (no Postgres required)."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
from httpx2 import ASGITransport, AsyncClient

from aiobs_server.config import get_settings
from aiobs_server.infrastructure.db import bootstrap_schema, dispose_db, init_db
from aiobs_server.main import create_app
from support.packaged_ui import requires_packaged_ui


@pytest.fixture
async def sqlite_client(tmp_path_factory: pytest.TempPathFactory) -> AsyncIterator[AsyncClient]:
    db_path = tmp_path_factory.mktemp("sqlite") / "aiobs.db"
    previous_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"
    get_settings.cache_clear()
    await dispose_db()
    init_db(get_settings())
    await bootstrap_schema()

    app = create_app(mount_packaged_ui=True)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    await dispose_db()
    if previous_url is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = previous_url
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_sqlite_health_and_project_create(sqlite_client: AsyncClient) -> None:
    health = await sqlite_client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    created = await sqlite_client.post(
        "/api/v1/projects",
        json={"name": "SQLite Demo", "slug": "sqlite-demo"},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["name"] == "SQLite Demo"
    assert body["slug"] == "sqlite-demo"
    assert body["created_at"].endswith("Z") or "+" in body["created_at"][10:]

    listed_after_reload = await sqlite_client.get(f"/api/v1/projects/{body['id']}")
    assert listed_after_reload.status_code == 200
    reloaded = listed_after_reload.json()["created_at"]
    assert reloaded.endswith("Z") or "+" in reloaded[10:]

    listed = await sqlite_client.get("/api/v1/projects")
    assert listed.status_code == 200
    assert any(p["slug"] == "sqlite-demo" for p in listed.json())


@requires_packaged_ui
@pytest.mark.asyncio
async def test_sqlite_ui_index_served(sqlite_client: AsyncClient) -> None:
    response = await sqlite_client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")


def _otlp_span(
    *,
    trace_id: str,
    span_id: str,
    name: str,
    start_nano: str,
    end_nano: str,
    parent_span_id: str | None = None,
) -> dict:
    span: dict = {
        "traceId": trace_id,
        "spanId": span_id,
        "name": name,
        "startTimeUnixNano": start_nano,
        "endTimeUnixNano": end_nano,
        "status": {"code": "STATUS_CODE_OK"},
        "attributes": [
            {"key": "openinference.span.kind", "value": {"stringValue": "CHAIN"}},
        ],
    }
    if parent_span_id is not None:
        span["parentSpanId"] = parent_span_id
    return span


def _otlp_payload(spans: list[dict]) -> dict:
    return {"resourceSpans": [{"scopeSpans": [{"spans": spans}]}]}


@pytest.mark.asyncio
async def test_sqlite_otlp_minimal(sqlite_client: AsyncClient) -> None:
    project = await sqlite_client.post(
        "/api/v1/projects",
        json={"name": "OTLP", "slug": "otlp-sqlite"},
    )
    assert project.status_code == 201

    response = await sqlite_client.post(
        "/v1/traces",
        json=_otlp_payload(
            [
                _otlp_span(
                    trace_id="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    span_id="bbbbbbbbbbbbbbbb",
                    name="hello",
                    start_nano="1700000000000000000",
                    end_nano="1700000001000000000",
                )
            ]
        ),
        headers={"X-Project-Slug": "otlp-sqlite"},
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_sqlite_otlp_upsert_same_trace_merges(sqlite_client: AsyncClient) -> None:
    """Second batch for the same trace must merge (SQLite naive vs aware datetimes)."""
    project = await sqlite_client.post(
        "/api/v1/projects",
        json={"name": "OTLP Merge", "slug": "otlp-sqlite-merge"},
    )
    assert project.status_code == 201

    headers = {"X-Project-Slug": "otlp-sqlite-merge"}
    trace_id = "cccccccccccccccccccccccccccccccc"

    first = await sqlite_client.post(
        "/v1/traces",
        json=_otlp_payload(
            [
                _otlp_span(
                    trace_id=trace_id,
                    span_id="1111111111111111",
                    name="parent",
                    start_nano="1700000000000000000",
                    end_nano="1700000002000000000",
                )
            ]
        ),
        headers=headers,
    )
    assert first.status_code == 200

    second = await sqlite_client.post(
        "/v1/traces",
        json=_otlp_payload(
            [
                _otlp_span(
                    trace_id=trace_id,
                    span_id="2222222222222222",
                    name="child",
                    start_nano="1700000000500000000",
                    end_nano="1700000001500000000",
                    parent_span_id="1111111111111111",
                )
            ]
        ),
        headers=headers,
    )
    assert second.status_code == 200

    project_id = project.json()["id"]
    listed = await sqlite_client.get(f"/api/v1/projects/{project_id}/traces/{trace_id}")
    assert listed.status_code == 200
    assert len(listed.json()["spans"]) == 2
