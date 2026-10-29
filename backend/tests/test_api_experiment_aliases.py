from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from opengrade_server.config import get_settings
from opengrade_server.infrastructure.db import bootstrap_schema, dispose_db, init_db
from opengrade_server.infrastructure.models import ExperimentModel
from opengrade_server.main import create_app


@pytest.fixture
async def env(
    tmp_path_factory: pytest.TempPathFactory,
) -> AsyncIterator[tuple[AsyncClient, async_sessionmaker[AsyncSession]]]:
    db_path = tmp_path_factory.mktemp("aliases") / "opengrade.db"
    previous_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"
    get_settings.cache_clear()
    await dispose_db()
    factory = init_db(get_settings())
    await bootstrap_schema()

    app = create_app(mount_packaged_ui=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, factory

    await dispose_db()
    if previous_url is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = previous_url
    get_settings.cache_clear()


async def _project(client: AsyncClient) -> str:
    response = await client.post("/api/v1/projects", json={"name": f"p-{uuid.uuid4().hex[:6]}"})
    assert response.status_code == 201
    return str(response.json()["id"])


async def _dataset(client: AsyncClient, project_id: str, name: str = "gold") -> str:
    response = await client.post(f"/api/v1/projects/{project_id}/datasets", json={"name": name})
    assert response.status_code == 201
    return str(response.json()["id"])


async def _experiment(
    client: AsyncClient,
    factory: async_sessionmaker[AsyncSession],
    project_id: str,
    dataset_id: str,
    *,
    version: str,
    status: str = "completed",
) -> dict[str, Any]:
    response = await client.post(
        f"/api/v1/projects/{project_id}/experiments",
        json={"name": "ci", "dataset_id": dataset_id, "version": version},
    )
    assert response.status_code == 201
    body: dict[str, Any] = response.json()
    async with factory() as session:
        await session.execute(
            update(ExperimentModel)
            .where(ExperimentModel.id == uuid.UUID(body["id"]))
            .values(status=status)
        )
        await session.commit()
    return body


@pytest.mark.asyncio
async def test_promote_moves_alias_and_records_history(
    env: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, factory = env
    project_id = await _project(client)
    dataset_id = await _dataset(client, project_id)
    first = await _experiment(client, factory, project_id, dataset_id, version="aaa111")
    second = await _experiment(client, factory, project_id, dataset_id, version="bbb222")
    url = f"/api/v1/projects/{project_id}/experiment-aliases/main"

    assert (await client.get(url)).status_code == 404

    created = await client.put(url, json={"experiment_id": first["id"], "note": "bootstrap"})
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["experiment_id"] == first["id"]
    assert body["experiment"]["version"] == "aaa111"
    assert body["previous_experiment_id"] is None
    assert body["changed"] is True

    moved = await client.put(url, json={"experiment_id": second["id"]})
    assert moved.status_code == 200, moved.text
    assert moved.json()["previous_experiment_id"] == first["id"]

    same = await client.put(url, json={"experiment_id": second["id"]})
    assert same.status_code == 200
    assert same.json()["changed"] is False

    current = (await client.get(url)).json()
    assert current["experiment_id"] == second["id"]
    assert current["experiment"]["version"] == "bbb222"

    history = (await client.get(f"{url}/history")).json()
    assert [e["experiment_id"] for e in history] == [second["id"], first["id"]]
    assert history[0]["previous_experiment_id"] == first["id"]
    assert history[1]["note"] == "bootstrap"

    listed = (await client.get(f"/api/v1/projects/{project_id}/experiment-aliases")).json()
    assert [a["name"] for a in listed] == ["main"]

    assert (await client.delete(url)).status_code == 204
    assert (await client.get(url)).status_code == 404
    assert (await client.delete(url)).status_code == 404


@pytest.mark.asyncio
async def test_promote_rejects_unfinished_and_foreign_experiments(
    env: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, factory = env
    project_id = await _project(client)
    other_project = await _project(client)
    dataset_id = await _dataset(client, project_id)
    running = await _experiment(
        client, factory, project_id, dataset_id, version="r", status="failed"
    )
    url = f"/api/v1/projects/{project_id}/experiment-aliases/main"

    refused = await client.put(url, json={"experiment_id": running["id"]})
    assert refused.status_code == 409
    assert "failed" in refused.json()["detail"]

    foreign = await client.put(
        f"/api/v1/projects/{other_project}/experiment-aliases/main",
        json={"experiment_id": running["id"]},
    )
    assert foreign.status_code == 404

    blank = await client.put(
        f"/api/v1/projects/{project_id}/experiment-aliases/%20",
        json={"experiment_id": running["id"]},
    )
    assert blank.status_code == 400

    unknown_project = await client.get(f"/api/v1/projects/{uuid.uuid4()}/experiment-aliases")
    assert unknown_project.status_code == 404


@pytest.mark.asyncio
async def test_exam_change_needs_force(
    env: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, factory = env
    project_id = await _project(client)
    gold_v1 = await _dataset(client, project_id, "gold-v1")
    gold_v2 = await _dataset(client, project_id, "gold-v2")
    old = await _experiment(client, factory, project_id, gold_v1, version="old")
    new = await _experiment(client, factory, project_id, gold_v2, version="new")
    url = f"/api/v1/projects/{project_id}/experiment-aliases/main"
    assert (await client.put(url, json={"experiment_id": old["id"]})).status_code == 200

    refused = await client.put(url, json={"experiment_id": new["id"]})
    assert refused.status_code == 409
    assert "dataset" in refused.json()["detail"]

    forced = await client.put(
        url, json={"experiment_id": new["id"], "force": True, "note": "new gold set"}
    )
    assert forced.status_code == 200
    assert forced.json()["experiment_id"] == new["id"]


@pytest.mark.asyncio
async def test_deleting_project_drops_aliases(
    env: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, factory = env
    project_id = await _project(client)
    dataset_id = await _dataset(client, project_id)
    exp = await _experiment(client, factory, project_id, dataset_id, version="v")
    url = f"/api/v1/projects/{project_id}/experiment-aliases/main"
    assert (await client.put(url, json={"experiment_id": exp["id"]})).status_code == 200

    assert (await client.delete(f"/api/v1/projects/{project_id}")).status_code == 204
    assert (await client.get(f"/api/v1/projects/{project_id}")).status_code == 404
