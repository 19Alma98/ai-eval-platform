from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine

from aiobs.infrastructure.db import dispose_db, init_db
from aiobs.infrastructure.models import Base
from aiobs.main import create_app

DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    os.getenv("DATABASE_URL", "postgresql+asyncpg://aiobs:aiobs@localhost:5434/aiobs"),
)

pytestmark = pytest.mark.integration


@pytest.fixture
async def client() -> AsyncClient:
    engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
    except Exception as exc:  # noqa: BLE001
        await engine.dispose()
        pytest.skip(f"PostgreSQL not available for integration tests: {exc}")

    await engine.dispose()

    os.environ["DATABASE_URL"] = DATABASE_URL
    from aiobs.config import get_settings

    get_settings.cache_clear()
    await dispose_db()
    init_db(get_settings())

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    await dispose_db()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_otlp_persist_list_get(client: AsyncClient) -> None:
    create_project = await client.post("/api/v1/projects", json={"name": "Trace Demo"})
    assert create_project.status_code == 201
    project_id = create_project.json()["id"]

    payload = {
        "resourceSpans": [
            {
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": "11" * 16,
                                "spanId": "22" * 8,
                                "name": "root",
                                "startTimeUnixNano": "1700000000000000000",
                                "endTimeUnixNano": "1700000001000000000",
                                "status": {"code": "STATUS_CODE_OK"},
                                "attributes": [
                                    {
                                        "key": "openinference.span.kind",
                                        "value": {"stringValue": "CHAIN"},
                                    }
                                ],
                            },
                            {
                                "traceId": "11" * 16,
                                "spanId": "33" * 8,
                                "parentSpanId": "22" * 8,
                                "name": "llm",
                                "startTimeUnixNano": "1700000000500000000",
                                "endTimeUnixNano": "1700000000900000000",
                                "status": {"code": "STATUS_CODE_OK"},
                                "attributes": [
                                    {
                                        "key": "openinference.span.kind",
                                        "value": {"stringValue": "LLM"},
                                    },
                                    {
                                        "key": "gen_ai.request.model",
                                        "value": {"stringValue": "gpt-4o-mini"},
                                    },
                                ],
                            },
                        ]
                    }
                ]
            }
        ]
    }

    otlp = await client.post(
        "/v1/traces",
        json=payload,
        headers={"X-Project-Slug": create_project.json()["slug"]},
    )
    assert otlp.status_code == 200

    listed = await client.get(f"/api/v1/projects/{project_id}/traces")
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert len(items) == 1
    assert items[0]["span_count"] == 2

    detail = await client.get(f"/api/v1/projects/{project_id}/traces/{'11' * 16}")
    assert detail.status_code == 200
    spans = detail.json()["spans"]
    kinds = {s["kind"] for s in spans}
    assert kinds == {"CHAIN", "LLM"}

    # upsert same trace_id merges additional spans (OTLP clients often export per-span)
    payload2 = {
        "resourceSpans": [
            {
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": "11" * 16,
                                "spanId": "44" * 8,
                                "name": "only",
                                "startTimeUnixNano": "1700000002000000000",
                                "endTimeUnixNano": "1700000003000000000",
                                "status": {"code": "STATUS_CODE_ERROR"},
                                "attributes": [
                                    {
                                        "key": "openinference.span.kind",
                                        "value": {"stringValue": "TOOL"},
                                    }
                                ],
                            }
                        ]
                    }
                ]
            }
        ]
    }
    again = await client.post(
        "/v1/traces",
        json=payload2,
        headers={"X-Project-Id": project_id},
    )
    assert again.status_code == 200
    detail2 = await client.get(f"/api/v1/projects/{project_id}/traces/{'11' * 16}")
    spans2 = detail2.json()["spans"]
    assert len(spans2) == 3
    kinds2 = {s["kind"] for s in spans2}
    assert kinds2 == {"CHAIN", "LLM", "TOOL"}
    assert detail2.json()["status"] == "error"


@pytest.mark.asyncio
async def test_rest_create_persisted(client: AsyncClient) -> None:
    create_project = await client.post("/api/v1/projects", json={"name": "REST Trace"})
    project_id = create_project.json()["id"]
    create = await client.post(
        f"/api/v1/projects/{project_id}/traces",
        json={
            "trace_id": "ab" * 16,
            "name": "manual",
            "status": "ok",
            "start_time": datetime.now(UTC).isoformat(),
            "spans": [],
        },
    )
    assert create.status_code == 201
    got = await client.get(f"/api/v1/projects/{project_id}/traces/{'ab' * 16}")
    assert got.status_code == 200
    assert uuid.UUID(got.json()["id"])
