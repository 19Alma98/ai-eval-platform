from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
import pytest
from httpx import ASGITransport, AsyncClient

from aiobs.api.deps import get_dataset_repository, get_project_repository
from aiobs.domain.dataset import Dataset
from aiobs.domain.project import Project
from aiobs.main import create_app
from tests.support.repositories import InMemoryExperimentRepository, wire_metrics_pack_repos


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


def _entry_payload(pack: dict, kind: str) -> dict:
    for entry in pack["entries"]:
        if entry["kind"] == kind:
            return {
                "kind": entry["kind"],
                "enabled": entry["enabled"],
                "threshold": entry["threshold"],
                "config": entry["config"],
                "evaluator_id": entry.get("evaluator_id"),
                "removable": entry["removable"],
            }
    raise KeyError(kind)


@pytest.mark.asyncio
async def test_ensure_creates_default_entries_with_evaluator_ids(
    client: tuple[AsyncClient, InMemoryExperimentRepository],
) -> None:
    ac, _ = client
    proj = (await ac.post("/api/v1/projects", json={"name": "P", "slug": "p-mp"})).json()
    resp = await ac.post(f"/api/v1/projects/{proj['id']}/metrics-pack/ensure")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["entries"]) == 5
    kinds = {e["kind"] for e in body["entries"]}
    assert kinds == {
        "hit_at_k",
        "must_contain",
        "groundedness",
        "correctness",
        "latency",
    }
    for entry in body["entries"]:
        assert entry["evaluator_id"] is not None

    again = await ac.post(f"/api/v1/projects/{proj['id']}/metrics-pack/ensure")
    assert again.status_code == 200
    assert again.json()["id"] == body["id"]


@pytest.mark.asyncio
async def test_put_cannot_drop_hit_at_k(
    client: tuple[AsyncClient, InMemoryExperimentRepository],
) -> None:
    ac, _ = client
    proj = (await ac.post("/api/v1/projects", json={"name": "P2", "slug": "p-mp2"})).json()
    ensured = (await ac.post(f"/api/v1/projects/{proj['id']}/metrics-pack/ensure")).json()
    entries = [
        _entry_payload(ensured, k)
        for k in ("must_contain", "groundedness", "correctness", "latency")
    ]
    bad = await ac.put(
        f"/api/v1/projects/{proj['id']}/metrics-pack",
        json={"entries": entries},
    )
    assert bad.status_code == 400


@pytest.mark.asyncio
async def test_put_can_disable_hit_at_k(
    client: tuple[AsyncClient, InMemoryExperimentRepository],
) -> None:
    ac, _ = client
    proj = (await ac.post("/api/v1/projects", json={"name": "P3", "slug": "p-mp3"})).json()
    ensured = (await ac.post(f"/api/v1/projects/{proj['id']}/metrics-pack/ensure")).json()
    entries = [
        _entry_payload(ensured, k)
        for k in ("hit_at_k", "must_contain", "groundedness", "correctness", "latency")
    ]
    hit = next(e for e in entries if e["kind"] == "hit_at_k")
    hit["enabled"] = False
    updated = await ac.put(
        f"/api/v1/projects/{proj['id']}/metrics-pack",
        json={"entries": entries},
    )
    assert updated.status_code == 200
    hit_entry = next(e for e in updated.json()["entries"] if e["kind"] == "hit_at_k")
    assert hit_entry["enabled"] is False


@pytest.mark.asyncio
async def test_put_rejects_foreign_or_unknown_evaluator_id(
    client: tuple[AsyncClient, InMemoryExperimentRepository],
) -> None:
    ac, _ = client
    proj_a = (await ac.post("/api/v1/projects", json={"name": "PA", "slug": "p-mp-a"})).json()
    proj_b = (await ac.post("/api/v1/projects", json={"name": "PB", "slug": "p-mp-b"})).json()
    ensured = (
        await ac.post(f"/api/v1/projects/{proj_a['id']}/metrics-pack/ensure")
    ).json()
    entries = [
        _entry_payload(ensured, k)
        for k in ("hit_at_k", "must_contain", "groundedness", "correctness", "latency")
    ]

    foreign_resp = await ac.post(
        f"/api/v1/projects/{proj_b['id']}/evaluators",
        json={
            "name": "exact",
            "type": "deterministic",
            "config": {"kind": "exact_match"},
        },
    )
    assert foreign_resp.status_code == 201
    foreign = foreign_resp.json()
    entries.append(
        {
            "kind": "custom_metric",
            "enabled": True,
            "threshold": None,
            "config": {},
            "evaluator_id": foreign["id"],
            "removable": True,
        }
    )
    bad_foreign = await ac.put(
        f"/api/v1/projects/{proj_a['id']}/metrics-pack",
        json={"entries": entries},
    )
    assert bad_foreign.status_code == 400

    entries[-1]["evaluator_id"] = str(uuid.uuid4())
    bad_unknown = await ac.put(
        f"/api/v1/projects/{proj_a['id']}/metrics-pack",
        json={"entries": entries},
    )
    assert bad_unknown.status_code == 400


@pytest.mark.asyncio
async def test_put_pack_conflict_when_experiment_pins_default(
    client: tuple[AsyncClient, InMemoryExperimentRepository],
) -> None:
    ac, experiments = client
    proj = (await ac.post("/api/v1/projects", json={"name": "P409", "slug": "p-mp409"})).json()
    pack = (await ac.post(f"/api/v1/projects/{proj['id']}/metrics-pack/ensure")).json()
    dataset = (
        await ac.post(
            f"/api/v1/projects/{proj['id']}/datasets",
            json={"name": "d409", "task_type": "rag_qa"},
        )
    ).json()
    exp_resp = await ac.post(
        f"/api/v1/projects/{proj['id']}/experiments",
        json={"name": "e409", "dataset_id": dataset["id"]},
    )
    assert exp_resp.status_code == 201
    stored = await experiments.get_by_id(uuid.UUID(exp_resp.json()["id"]))
    assert stored is not None
    await experiments.update(stored.with_metrics_set_id(uuid.UUID(pack["id"])))

    entries = [
        _entry_payload(pack, k)
        for k in ("hit_at_k", "must_contain", "groundedness", "correctness", "latency")
    ]
    conflict = await ac.put(
        f"/api/v1/projects/{proj['id']}/metrics-pack",
        json={"entries": entries},
    )
    assert conflict.status_code == 409


@pytest.mark.asyncio
async def test_rag_qa_dataset_create_auto_ensures_metrics_pack(
    client: tuple[AsyncClient, InMemoryExperimentRepository],
) -> None:
    ac, _ = client
    proj = (await ac.post("/api/v1/projects", json={"name": "P4", "slug": "p-mp4"})).json()
    missing = await ac.get(f"/api/v1/projects/{proj['id']}/metrics-pack")
    assert missing.status_code == 404

    await ac.post(
        f"/api/v1/projects/{proj['id']}/datasets",
        json={"name": "faq", "task_type": "rag_qa"},
    )
    pack = await ac.get(f"/api/v1/projects/{proj['id']}/metrics-pack")
    assert pack.status_code == 200
    assert len(pack.json()["entries"]) == 5
    assert all(e["evaluator_id"] for e in pack.json()["entries"])
