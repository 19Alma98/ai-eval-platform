from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from aiobs.api.deps import get_dataset_repository, get_project_repository
from aiobs.domain.dataset import Dataset
from aiobs.domain.project import Project
from aiobs.main import create_app
from tests.support.repositories import (
    InMemoryExperimentRepository,
    wire_metrics_pack_repos,
)


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

    async def add_item(self, item):  # noqa: ANN001
        raise NotImplementedError

    async def list_items(self, dataset_id: uuid.UUID):  # noqa: ANN001
        return []

    async def get_item(self, item_id: uuid.UUID):  # noqa: ANN001
        return None


@pytest.fixture
async def client() -> AsyncIterator[tuple[AsyncClient, InMemoryExperimentRepository]]:
    projects = InMemoryProjectRepository()
    datasets = InMemoryDatasetRepository()
    app = create_app()
    app.dependency_overrides[get_project_repository] = lambda: projects
    app.dependency_overrides[get_dataset_repository] = lambda: datasets
    _evaluators, _metrics_sets, experiments = wire_metrics_pack_repos(app)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, experiments
    app.dependency_overrides.clear()


def _single_hit_entry(pack: dict) -> dict:
    hit = next(e for e in pack["entries"] if e["kind"] == "hit_at_k")
    return {
        "kind": hit["kind"],
        "enabled": hit["enabled"],
        "threshold": hit["threshold"],
        "config": hit["config"],
        "evaluator_id": hit["evaluator_id"],
    }


async def _ensure_default(client: AsyncClient, slug: str) -> tuple[dict, dict]:
    proj = (await client.post("/api/v1/projects", json={"name": "P", "slug": slug})).json()
    pack = (await client.post(f"/api/v1/projects/{proj['id']}/metrics-pack/ensure")).json()
    return proj, pack


@pytest.mark.asyncio
async def test_list_includes_default_after_ensure(
    client: tuple[AsyncClient, InMemoryExperimentRepository],
) -> None:
    ac, _ = client
    proj, _pack = await _ensure_default(ac, "ms-list")
    listed = await ac.get(f"/api/v1/projects/{proj['id']}/metrics-sets")
    assert listed.status_code == 200
    body = listed.json()
    default = next(s for s in body if s["name"] == "Default" and s["version"] == 1)
    assert default["is_project_default"] is True
    assert default["entry_count"] == 8


@pytest.mark.asyncio
async def test_create_custom_v1_and_duplicate_name_version_conflict(
    client: tuple[AsyncClient, InMemoryExperimentRepository],
) -> None:
    ac, _ = client
    proj, pack = await _ensure_default(ac, "ms-create")
    payload = {"name": "Custom", "entries": [_single_hit_entry(pack)]}
    created = await ac.post(f"/api/v1/projects/{proj['id']}/metrics-sets", json=payload)
    assert created.status_code == 201
    body = created.json()
    assert body["version"] == 1
    assert body["is_project_default"] is False

    again = await ac.post(f"/api/v1/projects/{proj['id']}/metrics-sets", json=payload)
    assert again.status_code == 409


@pytest.mark.asyncio
async def test_get_custom_set_entries_have_is_default_false(
    client: tuple[AsyncClient, InMemoryExperimentRepository],
) -> None:
    ac, _ = client
    proj, pack = await _ensure_default(ac, "ms-get")
    created = (
        await ac.post(
            f"/api/v1/projects/{proj['id']}/metrics-sets",
            json={"name": "Alt", "entries": [_single_hit_entry(pack)]},
        )
    ).json()
    detail = await ac.get(f"/api/v1/metrics-sets/{created['id']}")
    assert detail.status_code == 200
    for entry in detail.json()["entries"]:
        assert entry["is_default"] is False


@pytest.mark.asyncio
async def test_patch_unreferenced_ok_referenced_conflict(
    client: tuple[AsyncClient, InMemoryExperimentRepository],
) -> None:
    ac, experiments = client
    proj, pack = await _ensure_default(ac, "ms-patch")
    custom = (
        await ac.post(
            f"/api/v1/projects/{proj['id']}/metrics-sets",
            json={"name": "PatchMe", "entries": [_single_hit_entry(pack)]},
        )
    ).json()
    ok = await ac.patch(
        f"/api/v1/metrics-sets/{custom['id']}",
        json={"name": "PatchMeRenamed"},
    )
    assert ok.status_code == 200

    dataset = (
        await ac.post(
            f"/api/v1/projects/{proj['id']}/datasets",
            json={"name": "d", "task_type": "rag_qa"},
        )
    ).json()
    exp_resp = await ac.post(
        f"/api/v1/projects/{proj['id']}/experiments",
        json={"name": "e", "dataset_id": dataset["id"]},
    )
    assert exp_resp.status_code == 201
    exp = exp_resp.json()
    stored = await experiments.get_by_id(uuid.UUID(exp["id"]))
    assert stored is not None
    await experiments.update(stored.with_metrics_set_id(uuid.UUID(custom["id"])))

    blocked = await ac.patch(
        f"/api/v1/metrics-sets/{custom['id']}",
        json={"name": "Blocked"},
    )
    assert blocked.status_code == 409


@pytest.mark.asyncio
async def test_version_creates_v2_without_stealing_default(
    client: tuple[AsyncClient, InMemoryExperimentRepository],
) -> None:
    ac, _ = client
    proj, pack = await _ensure_default(ac, "ms-version")
    default_id = pack["id"]
    v2 = await ac.post(f"/api/v1/metrics-sets/{default_id}/version", json={})
    assert v2.status_code == 201
    body = v2.json()
    assert body["version"] == 2
    assert body["is_project_default"] is False
    assert all(e["is_default"] is False for e in body["entries"])

    source = await ac.get(f"/api/v1/metrics-sets/{default_id}")
    assert source.status_code == 200
    assert source.json()["version"] == 1
    assert source.json()["is_project_default"] is True


@pytest.mark.asyncio
async def test_delete_default_conflict_custom_ok(
    client: tuple[AsyncClient, InMemoryExperimentRepository],
) -> None:
    ac, _ = client
    proj, pack = await _ensure_default(ac, "ms-delete")
    default_id = pack["id"]
    assert (await ac.delete(f"/api/v1/metrics-sets/{default_id}")).status_code == 409

    custom = (
        await ac.post(
            f"/api/v1/projects/{proj['id']}/metrics-sets",
            json={"name": "Trash", "entries": [_single_hit_entry(pack)]},
        )
    ).json()
    assert (await ac.delete(f"/api/v1/metrics-sets/{custom['id']}")).status_code == 204
    assert (await ac.get(f"/api/v1/metrics-sets/{custom['id']}")).status_code == 404


@pytest.mark.asyncio
async def test_delete_entry_default_seed_vs_version_copy(
    client: tuple[AsyncClient, InMemoryExperimentRepository],
) -> None:
    ac, _ = client
    proj, pack = await _ensure_default(ac, "ms-entry-del")
    default_id = pack["id"]
    detail = (await ac.get(f"/api/v1/metrics-sets/{default_id}")).json()
    hit_id = next(e["id"] for e in detail["entries"] if e["kind"] == "hit_at_k")
    assert (
        await ac.delete(f"/api/v1/metrics-sets/{default_id}/entries/{hit_id}")
    ).status_code == 409

    v2 = (await ac.post(f"/api/v1/metrics-sets/{default_id}/version", json={})).json()
    hit_v2 = next(e for e in v2["entries"] if e["kind"] == "must_contain")
    removed = await ac.delete(
        f"/api/v1/metrics-sets/{v2['id']}/entries/{hit_v2['id']}",
    )
    assert removed.status_code == 200
    kinds = {e["kind"] for e in removed.json()["entries"]}
    assert "must_contain" not in kinds


@pytest.mark.asyncio
async def test_get_and_patch_unknown_metrics_set_404(
    client: tuple[AsyncClient, InMemoryExperimentRepository],
) -> None:
    ac, _ = client
    missing = uuid.uuid4()
    assert (await ac.get(f"/api/v1/metrics-sets/{missing}")).status_code == 404
    assert (
        await ac.patch(f"/api/v1/metrics-sets/{missing}", json={"name": "x"})
    ).status_code == 404


@pytest.mark.asyncio
async def test_list_and_create_unknown_project_404(
    client: tuple[AsyncClient, InMemoryExperimentRepository],
) -> None:
    ac, _ = client
    missing_project = uuid.uuid4()
    listed = await ac.get(f"/api/v1/projects/{missing_project}/metrics-sets")
    assert listed.status_code == 404

    created = await ac.post(
        f"/api/v1/projects/{missing_project}/metrics-sets",
        json={
            "name": "Orphan",
            "entries": [
                {
                    "kind": "hit_at_k",
                    "enabled": True,
                    "threshold": None,
                    "config": {"k": 5},
                    "evaluator_id": None,
                }
            ],
        },
    )
    assert created.status_code == 404


@pytest.mark.asyncio
async def test_delete_unknown_entry_not_same_as_unknown_set(
    client: tuple[AsyncClient, InMemoryExperimentRepository],
) -> None:
    ac, _ = client
    proj, pack = await _ensure_default(ac, "ms-entry-404")
    missing_entry = uuid.uuid4()
    on_set = await ac.delete(
        f"/api/v1/metrics-sets/{pack['id']}/entries/{missing_entry}",
    )
    assert on_set.status_code == 404
    assert "entry" in on_set.json()["detail"].lower()

    missing_set = uuid.uuid4()
    on_missing_set = await ac.delete(
        f"/api/v1/metrics-sets/{missing_set}/entries/{missing_entry}",
    )
    assert on_missing_set.status_code == 404
    assert "Metrics set not found" in on_missing_set.json()["detail"]
