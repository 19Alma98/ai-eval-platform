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


async def _rag_qa_dataset(client: AsyncClient) -> str:
    proj = (await client.post("/api/v1/projects", json={"name": "P", "slug": "p-import"})).json()
    ds = (
        await client.post(
            f"/api/v1/projects/{proj['id']}/datasets",
            json={"name": "import-set", "task_type": "rag_qa"},
        )
    ).json()
    return ds["id"]


@pytest.mark.asyncio
async def test_import_csv_happy_path(client: AsyncClient) -> None:
    ds_id = await _rag_qa_dataset(client)
    csv_body = (
        "question,expected_answer,expected_doc_ids\n"
        "What is X?,Answer X,doc-1|doc-2\n"
        "What is Y?,Answer Y,doc-3\n"
    )
    resp = await client.post(
        f"/api/v1/datasets/{ds_id}/items/import",
        files={"file": ("items.csv", csv_body, "text/csv")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["created"] == 2
    assert data["errors"] == []

    detail = await client.get(f"/api/v1/datasets/{ds_id}")
    assert len(detail.json()["items"]) == 2


@pytest.mark.asyncio
async def test_import_csv_one_bad_row(client: AsyncClient) -> None:
    ds_id = await _rag_qa_dataset(client)
    csv_body = (
        "question,expected_answer,expected_doc_ids\n"
        "Good?,Good answer,doc-1\n"
        ",missing question,doc-2\n"
    )
    resp = await client.post(
        f"/api/v1/datasets/{ds_id}/items/import",
        files={"file": ("items.csv", csv_body, "text/csv")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["created"] == 1
    assert len(data["errors"]) == 1
    assert data["errors"][0]["row"] == 3
    assert "question" in data["errors"][0]["message"].lower()


@pytest.mark.asyncio
async def test_import_csv_missing_header_column(client: AsyncClient) -> None:
    ds_id = await _rag_qa_dataset(client)
    csv_body = "question,expected_answer\nQ?,A\n"
    resp = await client.post(
        f"/api/v1/datasets/{ds_id}/items/import",
        files={"file": ("items.csv", csv_body, "text/csv")},
    )
    assert resp.status_code in (400, 422)
    assert "expected_doc_ids" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_import_json_happy_path(client: AsyncClient) -> None:
    ds_id = await _rag_qa_dataset(client)
    payload = [
        {
            "question": "Q1?",
            "expected_answer": "A1",
            "expected_doc_ids": ["d1", "d2"],
        },
    ]
    resp = await client.post(
        f"/api/v1/datasets/{ds_id}/items/import",
        files={"file": ("items.json", __import__("json").dumps(payload), "application/json")},
    )
    assert resp.status_code == 200
    assert resp.json()["created"] == 1


@pytest.mark.asyncio
async def test_import_all_rows_invalid_still_200(client: AsyncClient) -> None:
    ds_id = await _rag_qa_dataset(client)
    csv_body = (
        "question,expected_answer,expected_doc_ids\n"
        ",,\n"
    )
    resp = await client.post(
        f"/api/v1/datasets/{ds_id}/items/import",
        files={"file": ("items.csv", csv_body, "text/csv")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["created"] == 0
    assert len(data["errors"]) >= 1


@pytest.mark.asyncio
async def test_import_invalid_utf8_returns_422(client: AsyncClient) -> None:
    ds_id = await _rag_qa_dataset(client)
    resp = await client.post(
        f"/api/v1/datasets/{ds_id}/items/import",
        files={"file": ("items.csv", b"\xff\xfe", "text/csv")},
    )
    assert resp.status_code == 422
    assert "utf-8" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_import_non_rag_qa_dataset_returns_400(client: AsyncClient) -> None:
    proj = (await client.post("/api/v1/projects", json={"name": "P2", "slug": "p2-import"})).json()
    ds = (
        await client.post(
            f"/api/v1/projects/{proj['id']}/datasets",
            json={"name": "generic", "task_type": "classification"},
        )
    ).json()
    csv_body = "question,expected_answer,expected_doc_ids\nQ?,A,doc-1\n"
    resp = await client.post(
        f"/api/v1/datasets/{ds['id']}/items/import",
        files={"file": ("items.csv", csv_body, "text/csv")},
    )
    assert resp.status_code == 400
