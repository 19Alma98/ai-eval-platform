from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from httpx2 import ASGITransport, AsyncClient

from opengrade_server.api.deps import (
    get_dataset_repository,
    get_project_repository,
)
from opengrade_server.domain.dataset import Dataset, DatasetItem
from opengrade_server.domain.project import Project
from opengrade_server.main import create_app
from tests.support.repositories import wire_metrics_pack_repos


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
        return list(self._projects.values())


class InMemoryDatasetRepository:
    def __init__(self) -> None:
        self._datasets: dict[uuid.UUID, Dataset] = {}
        self._items: dict[uuid.UUID, DatasetItem] = {}

    async def add(self, dataset: Dataset) -> Dataset:
        self._datasets[dataset.id] = dataset
        return dataset

    async def get_by_id(self, dataset_id: uuid.UUID) -> Dataset | None:
        return self._datasets.get(dataset_id)

    async def list_by_project(
        self,
        project_id: uuid.UUID,
        *,
        task_type: str | None = None,
    ) -> list[Dataset]:
        return [
            d
            for d in self._datasets.values()
            if d.project_id == project_id and (task_type is None or d.task_type == task_type)
        ]

    async def add_item(self, item: DatasetItem) -> DatasetItem:
        self._items[item.id] = item
        return item

    async def count_items(self, dataset_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
        return {d: len(await self.list_items(d)) for d in dataset_ids}

    async def list_items(self, dataset_id: uuid.UUID) -> list[DatasetItem]:
        return [i for i in self._items.values() if i.dataset_id == dataset_id]

    async def get_item(self, item_id: uuid.UUID) -> DatasetItem | None:
        return self._items.get(item_id)

    async def delete(self, dataset_id: uuid.UUID) -> bool:
        if dataset_id not in self._datasets:
            return False
        del self._datasets[dataset_id]
        self._items = {
            item_id: item for item_id, item in self._items.items() if item.dataset_id != dataset_id
        }
        return True


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    projects = InMemoryProjectRepository()
    datasets = InMemoryDatasetRepository()
    app = create_app()
    app.dependency_overrides[get_project_repository] = lambda: projects
    app.dependency_overrides[get_dataset_repository] = lambda: datasets
    wire_metrics_pack_repos(app)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def _project_and_dataset(client: AsyncClient) -> tuple[str, str]:
    proj = (await client.post("/api/v1/projects", json={"name": "P", "slug": "p-ds-del"})).json()
    ds = (
        await client.post(
            f"/api/v1/projects/{proj['id']}/datasets",
            json={"name": "to-delete", "task_type": "rag_qa"},
        )
    ).json()
    return proj["id"], ds["id"]


@pytest.mark.asyncio
async def test_delete_dataset_happy_path(client: AsyncClient) -> None:
    _project_id, ds_id = await _project_and_dataset(client)
    item = await client.post(
        f"/api/v1/datasets/{ds_id}/items",
        json={
            "input": "Q?",
            "expected_output": "A",
            "metadata": {"expected_doc_ids": ["doc-1"]},
        },
    )
    assert item.status_code == 201

    resp = await client.delete(f"/api/v1/datasets/{ds_id}")
    assert resp.status_code == 204

    missing = await client.get(f"/api/v1/datasets/{ds_id}")
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_delete_dataset_not_found(client: AsyncClient) -> None:
    resp = await client.delete(f"/api/v1/datasets/{uuid.uuid4()}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_dataset_blocked_by_experiments(client: AsyncClient) -> None:
    project_id, ds_id = await _project_and_dataset(client)
    exp_a = await client.post(
        f"/api/v1/projects/{project_id}/experiments",
        json={"name": "Baseline", "dataset_id": ds_id},
    )
    exp_b = await client.post(
        f"/api/v1/projects/{project_id}/experiments",
        json={"name": "Prompt v2", "dataset_id": ds_id},
    )
    assert exp_a.status_code == 201
    assert exp_b.status_code == 201

    resp = await client.delete(f"/api/v1/datasets/{ds_id}")
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert "Cannot delete test set" in detail
    assert "Baseline" in detail
    assert "Prompt v2" in detail
    assert exp_a.json()["id"] in detail
    assert exp_b.json()["id"] in detail

    still_there = await client.get(f"/api/v1/datasets/{ds_id}")
    assert still_there.status_code == 200
