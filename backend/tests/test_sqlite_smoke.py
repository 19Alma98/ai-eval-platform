"""SQLite local-mode smoke (no Postgres required)."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
from httpx2 import ASGITransport, AsyncClient

from aiobs_server.config import get_settings
from aiobs_server.infrastructure.db import bootstrap_schema, dispose_db, init_db
from aiobs_server.main import create_app


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
    assert body["slug"] == "sqlite-demo"

    listed = await sqlite_client.get("/api/v1/projects")
    assert listed.status_code == 200
    assert any(p["slug"] == "sqlite-demo" for p in listed.json())


@pytest.mark.asyncio
async def test_sqlite_ui_index_served(sqlite_client: AsyncClient) -> None:
    response = await sqlite_client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")


@pytest.mark.asyncio
async def test_sqlite_otlp_minimal(sqlite_client: AsyncClient) -> None:
    project = await sqlite_client.post(
        "/api/v1/projects",
        json={"name": "OTLP", "slug": "otlp-sqlite"},
    )
    assert project.status_code == 201

    payload = {
        "resourceSpans": [
            {
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                                "spanId": "bbbbbbbbbbbbbbbb",
                                "name": "hello",
                                "startTimeUnixNano": "1700000000000000000",
                                "endTimeUnixNano": "1700000001000000000",
                                "status": {"code": "STATUS_CODE_OK"},
                                "attributes": [
                                    {
                                        "key": "openinference.span.kind",
                                        "value": {"stringValue": "CHAIN"},
                                    }
                                ],
                            }
                        ]
                    }
                ]
            }
        ]
    }
    response = await sqlite_client.post(
        "/v1/traces",
        json=payload,
        headers={"X-Project-Slug": "otlp-sqlite"},
    )
    assert response.status_code == 200
