from __future__ import annotations

import os

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
async def test_compare_persisted(client: AsyncClient) -> None:
    project = await client.post("/api/v1/projects", json={"name": "Compare PG"})
    assert project.status_code == 201
    project_id = project.json()["id"]

    good = await client.post(
        f"/api/v1/projects/{project_id}/datasets",
        json={"name": "good"},
    )
    good_id = good.json()["id"]
    await client.post(
        f"/api/v1/datasets/{good_id}/items",
        json={"input": "q", "expected_output": "a", "actual_output": "a"},
    )

    bad = await client.post(
        f"/api/v1/projects/{project_id}/datasets",
        json={"name": "bad"},
    )
    bad_id = bad.json()["id"]
    await client.post(
        f"/api/v1/datasets/{bad_id}/items",
        json={"input": "q", "expected_output": "a", "actual_output": "b"},
    )

    evaluator = await client.post(
        f"/api/v1/projects/{project_id}/evaluators",
        json={
            "name": "exact",
            "type": "deterministic",
            "config": {"kind": "exact_match"},
        },
    )
    evaluator_id = evaluator.json()["id"]

    baseline = await client.post(
        f"/api/v1/projects/{project_id}/experiments",
        json={"name": "baseline", "dataset_id": good_id},
    )
    baseline_id = baseline.json()["id"]
    candidate = await client.post(
        f"/api/v1/projects/{project_id}/experiments",
        json={"name": "candidate", "dataset_id": bad_id},
    )
    candidate_id = candidate.json()["id"]

    for experiment_id in (baseline_id, candidate_id):
        evaluated = await client.post(
            f"/api/v1/experiments/{experiment_id}/evaluate",
            json={"evaluator_ids": [evaluator_id]},
        )
        assert evaluated.status_code == 200

    summary = await client.get(f"/api/v1/experiments/{baseline_id}/summary")
    assert summary.status_code == 200
    assert summary.json()["evaluators"][0]["mean_score"] == 1.0

    compare = await client.get(f"/api/v1/experiments/{candidate_id}/compare/{baseline_id}")
    assert compare.status_code == 200
    assert all(m["status"] == "regression" for m in compare.json()["metrics"])
