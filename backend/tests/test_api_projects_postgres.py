from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

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
