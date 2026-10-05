from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from aiobs.api.deps import get_dataset_repository, get_project_repository
from aiobs.domain.dataset import Dataset, DatasetItem
from aiobs.domain.project import Project
from aiobs.main import create_app
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

    async def list_items(self, dataset_id: uuid.UUID) -> list[DatasetItem]:
        return [i for i in self._items.values() if i.dataset_id == dataset_id]

    async def get_item(self, item_id: uuid.UUID) -> DatasetItem | None:
        return self._items.get(item_id)


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


@pytest.mark.asyncio
async def test_list_task_types(client: AsyncClient) -> None:
    res = await client.get("/api/v1/task-types")
    assert res.status_code == 200
    body = res.json()
    ids = {t["id"] for t in body}
    assert ids == {"rag_qa", "classification", "agent_tools"}
    rag = next(t for t in body if t["id"] == "rag_qa")
    assert "groundedness" in rag["recommended_evaluator_kinds"]
    assert rag["field_hints"]


@pytest.mark.asyncio
async def test_create_dataset_with_task_type(client: AsyncClient) -> None:
    project = await client.post("/api/v1/projects", json={"name": "Task Types"})
    project_id = project.json()["id"]

    created = await client.post(
        f"/api/v1/projects/{project_id}/datasets",
        json={"name": "faq", "task_type": "rag_qa"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["task_type"] == "rag_qa"

    listed = await client.get(
        f"/api/v1/projects/{project_id}/datasets",
        params={"task_type": "rag_qa"},
    )
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    empty = await client.get(
        f"/api/v1/projects/{project_id}/datasets",
        params={"task_type": "classification"},
    )
    assert empty.status_code == 200
    assert empty.json() == []


@pytest.mark.asyncio
async def test_create_dataset_rejects_unknown_task_type(client: AsyncClient) -> None:
    project = await client.post("/api/v1/projects", json={"name": "Bad Type"})
    project_id = project.json()["id"]

    res = await client.post(
        f"/api/v1/projects/{project_id}/datasets",
        json={"name": "x", "task_type": "not_a_type"},
    )
    assert res.status_code == 400
