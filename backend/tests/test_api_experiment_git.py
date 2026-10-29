from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator

import pytest
from httpx2 import ASGITransport, AsyncClient

from opengrade_server.config import get_settings
from opengrade_server.infrastructure.db import bootstrap_schema, dispose_db, init_db
from opengrade_server.main import create_app


@pytest.fixture
async def client(tmp_path_factory: pytest.TempPathFactory) -> AsyncIterator[AsyncClient]:
    db_path = tmp_path_factory.mktemp("git") / "opengrade.db"
    previous_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"
    get_settings.cache_clear()
    await dispose_db()
    init_db(get_settings())
    await bootstrap_schema()

    app = create_app(mount_packaged_ui=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http

    await dispose_db()
    if previous_url is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = previous_url
    get_settings.cache_clear()


async def _project_and_dataset(client: AsyncClient) -> tuple[str, str]:
    project = await client.post("/api/v1/projects", json={"name": f"p-{uuid.uuid4().hex[:6]}"})
    project_id = project.json()["id"]
    dataset = await client.post(f"/api/v1/projects/{project_id}/datasets", json={"name": "gold"})
    return project_id, dataset.json()["id"]


@pytest.mark.asyncio
async def test_experiment_persists_git_revision(client: AsyncClient) -> None:
    project_id, dataset_id = await _project_and_dataset(client)
    git = {
        "commit": "0123456789abcdef0123456789abcdef01234567",
        "branch": "feature/rerank",
        "dirty": True,
        "remote_url": "https://github.com/acme/app",
    }

    created = await client.post(
        f"/api/v1/projects/{project_id}/experiments",
        json={"name": "cand", "dataset_id": dataset_id, "version": "0123456789ab", "git": git},
    )
    assert created.status_code == 201, created.text
    assert created.json()["git"] == git

    fetched = await client.get(f"/api/v1/experiments/{created.json()['id']}")
    assert fetched.json()["git"] == git

    plain = await client.post(
        f"/api/v1/projects/{project_id}/experiments",
        json={"name": "plain", "dataset_id": dataset_id},
    )
    assert plain.json()["git"] is None


@pytest.mark.asyncio
async def test_experiment_rejects_non_hex_commit(client: AsyncClient) -> None:
    project_id, dataset_id = await _project_and_dataset(client)

    response = await client.post(
        f"/api/v1/projects/{project_id}/experiments",
        json={"name": "bad", "dataset_id": dataset_id, "git": {"commit": "main"}},
    )
    assert response.status_code == 422
