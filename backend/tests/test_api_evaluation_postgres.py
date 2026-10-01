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
    os.environ["CONTENT_CAPTURE_ENABLED"] = "true"
    from aiobs.config import get_settings

    get_settings.cache_clear()
    await dispose_db()
    init_db(get_settings())

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    await dispose_db()
    os.environ.pop("CONTENT_CAPTURE_ENABLED", None)
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_evaluate_persisted(client: AsyncClient) -> None:
    project = await client.post("/api/v1/projects", json={"name": "Eval PG"})
    assert project.status_code == 201
    project_id = project.json()["id"]

    dataset = await client.post(
        f"/api/v1/projects/{project_id}/datasets",
        json={"name": "ds1"},
    )
    assert dataset.status_code == 201
    dataset_id = dataset.json()["id"]

    item = await client.post(
        f"/api/v1/datasets/{dataset_id}/items",
        json={"input": "q", "expected_output": "a", "actual_output": "a"},
    )
    assert item.status_code == 201

    evaluator = await client.post(
        f"/api/v1/projects/{project_id}/evaluators",
        json={
            "name": "exact",
            "type": "deterministic",
            "config": {"kind": "exact_match"},
        },
    )
    assert evaluator.status_code == 201
    evaluator_id = evaluator.json()["id"]

    experiment = await client.post(
        f"/api/v1/projects/{project_id}/experiments",
        json={"name": "exp1", "dataset_id": dataset_id},
    )
    assert experiment.status_code == 201
    experiment_id = experiment.json()["id"]

    evaluated = await client.post(
        f"/api/v1/experiments/{experiment_id}/evaluate",
        json={"evaluator_ids": [evaluator_id]},
    )
    assert evaluated.status_code == 200
    run_id = evaluated.json()["runs"][0]["id"]

    detail = await client.get(f"/api/v1/evaluation-runs/{run_id}")
    assert detail.status_code == 200
    assert detail.json()["results"][0]["score"] == 1.0
    assert uuid.UUID(detail.json()["id"])


@pytest.mark.asyncio
async def test_from_trace_persisted(client: AsyncClient) -> None:
    project = await client.post("/api/v1/projects", json={"name": "Trace DS"})
    project_id = project.json()["id"]

    start = datetime(2024, 1, 1, tzinfo=UTC).isoformat()
    end = datetime(2024, 1, 1, 0, 0, 1, tzinfo=UTC).isoformat()
    create_trace = await client.post(
        f"/api/v1/projects/{project_id}/traces",
        json={
            "trace_id": "11" * 16,
            "name": "chat",
            "status": "ok",
            "start_time": start,
            "end_time": end,
            "input": {"q": "hi"},
            "output": {"a": "yo"},
            "spans": [
                {
                    "span_id": "22" * 8,
                    "name": "llm",
                    "kind": "LLM",
                    "start_time": start,
                    "end_time": end,
                    "status": "ok",
                    "attributes": {"gen_ai.usage.total_tokens": 7},
                }
            ],
        },
    )
    assert create_trace.status_code in {200, 201}, create_trace.text

    dataset = await client.post(
        f"/api/v1/projects/{project_id}/datasets",
        json={"name": "from-trace-pg"},
    )
    dataset_id = dataset.json()["id"]

    item = await client.post(
        f"/api/v1/datasets/{dataset_id}/items/from-trace",
        json={"trace_id": "11" * 16},
    )
    assert item.status_code == 201
    assert item.json()["actual_output"] == {"a": "yo"}
    assert item.json()["context"]["total_tokens"] == 7
