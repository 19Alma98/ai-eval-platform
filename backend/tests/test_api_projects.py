from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient

from aiobs.api.deps import get_project_repository
from aiobs.domain.project import Project
from aiobs.main import create_app


class InMemoryProjectRepository:
    def __init__(self) -> None:
        self._projects: dict[uuid.UUID, Project] = {}

    async def add(self, project: Project) -> Project:
        self._projects[project.id] = project
        return project

    async def get_by_id(self, project_id: uuid.UUID) -> Project | None:
        return self._projects.get(project_id)

    async def get_by_slug(self, slug: str) -> Project | None:
        for project in self._projects.values():
            if project.slug == slug:
                return project
        return None

    async def list_all(self) -> list[Project]:
        return sorted(
            self._projects.values(),
            key=lambda project: project.created_at or datetime.now(UTC),
            reverse=True,
        )


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    repo = InMemoryProjectRepository()
    app = create_app()
    app.dependency_overrides[get_project_repository] = lambda: repo

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_health(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_create_and_list_projects(client: AsyncClient) -> None:
    create = await client.post("/api/v1/projects", json={"name": "Demo"})
    assert create.status_code == 201
    body = create.json()
    assert body["name"] == "Demo"
    assert body["slug"] == "demo"
    assert uuid.UUID(body["id"])

    listed = await client.get("/api/v1/projects")
    assert listed.status_code == 200
    items = listed.json()
    assert len(items) == 1
    assert items[0]["id"] == body["id"]


@pytest.mark.asyncio
async def test_get_project(client: AsyncClient) -> None:
    create = await client.post("/api/v1/projects", json={"name": "Alpha", "slug": "alpha"})
    project_id = create.json()["id"]

    got = await client.get(f"/api/v1/projects/{project_id}")
    assert got.status_code == 200
    assert got.json()["slug"] == "alpha"

    missing = await client.get(f"/api/v1/projects/{uuid.uuid4()}")
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_slug_conflict(client: AsyncClient) -> None:
    first = await client.post("/api/v1/projects", json={"name": "One", "slug": "dup"})
    assert first.status_code == 201
    second = await client.post("/api/v1/projects", json={"name": "Two", "slug": "dup"})
    assert second.status_code == 409
