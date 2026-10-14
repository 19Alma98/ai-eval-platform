from __future__ import annotations

import uuid

import pytest
from httpx2 import AsyncClient

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_health_with_postgres(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_create_project_persisted(client: AsyncClient) -> None:
    create = await client.post("/api/v1/projects", json={"name": "Persisted"})
    assert create.status_code == 201
    project_id = create.json()["id"]

    got = await client.get(f"/api/v1/projects/{project_id}")
    assert got.status_code == 200
    assert got.json()["name"] == "Persisted"
    assert uuid.UUID(got.json()["id"]) == uuid.UUID(project_id)


@pytest.mark.asyncio
async def test_delete_project_with_metrics_set(client: AsyncClient) -> None:
    """Project delete must clear RESTRICT sibling FKs (metrics↔evaluators, experiments↔datasets)."""
    create = await client.post(
        "/api/v1/projects", json={"name": "With Metrics", "slug": "with-metrics"}
    )
    assert create.status_code == 201
    project_id = create.json()["id"]

    ensure = await client.post(f"/api/v1/projects/{project_id}/metrics-pack/ensure")
    assert ensure.status_code == 200
    assert ensure.json()["entries"]

    dataset = await client.post(
        f"/api/v1/projects/{project_id}/datasets",
        json={"name": "ds", "items": [{"input": {"q": "1"}}]},
    )
    assert dataset.status_code == 201
    experiment = await client.post(
        f"/api/v1/projects/{project_id}/experiments",
        json={"name": "e", "dataset_id": dataset.json()["id"]},
    )
    assert experiment.status_code == 201

    deleted = await client.delete(f"/api/v1/projects/{project_id}")
    assert deleted.status_code == 204

    missing = await client.get(f"/api/v1/projects/{project_id}")
    assert missing.status_code == 404
