"""List endpoints must 404 for unknown project_id (not empty 200)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from httpx2 import ASGITransport, AsyncClient

from opengrade_server.main import create_app
from tests.support.repositories import wire_metrics_pack_repos
from tests.test_api_live_interactions import InMemoryProjectRepository


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    projects = InMemoryProjectRepository()
    app = create_app()
    from opengrade_server.api.deps import get_project_repository

    app.dependency_overrides[get_project_repository] = lambda: projects
    wire_metrics_pack_repos(app)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path_suffix",
    [
        "live-interactions",
        "experiments",
        "evaluators",
        "datasets",
        "app-configs",
    ],
)
async def test_list_unknown_project_returns_404(client: AsyncClient, path_suffix: str) -> None:
    missing = uuid.uuid4()
    resp = await client.get(f"/api/v1/projects/{missing}/{path_suffix}")
    assert resp.status_code == 404, resp.text
