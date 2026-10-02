from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from tests.test_api_app_configs import InMemoryAppConfigRepository, InMemoryProjectRepository

from aiobs.api.deps import (
    get_app_config_repository,
    get_dataset_repository,
    get_experiment_repository,
    get_project_repository,
)
from aiobs.domain.dataset import Dataset
from aiobs.domain.experiment import Experiment
from aiobs.main import create_app


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

    async def add_item(self, item: Any) -> Any:
        raise NotImplementedError

    async def list_items(self, dataset_id: uuid.UUID) -> list[Any]:
        return []

    async def get_item(self, item_id: uuid.UUID) -> Any | None:
        return None


class InMemoryExperimentRepository:
    def __init__(self) -> None:
        self._items: dict[uuid.UUID, Experiment] = {}

    async def add(self, experiment: Experiment) -> Experiment:
        self._items[experiment.id] = experiment
        return experiment

    async def get_by_id(self, experiment_id: uuid.UUID) -> Experiment | None:
        return self._items.get(experiment_id)

    async def list_by_project(self, project_id: uuid.UUID) -> list[Experiment]:
        return [e for e in self._items.values() if e.project_id == project_id]

    async def update(self, experiment: Experiment) -> Experiment:
        self._items[experiment.id] = experiment
        return experiment


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    projects = InMemoryProjectRepository()
    app_configs = InMemoryAppConfigRepository()
    datasets = InMemoryDatasetRepository()
    experiments = InMemoryExperimentRepository()

    app = create_app()
    app.dependency_overrides[get_project_repository] = lambda: projects
    app.dependency_overrides[get_app_config_repository] = lambda: app_configs
    app.dependency_overrides[get_dataset_repository] = lambda: datasets
    app.dependency_overrides[get_experiment_repository] = lambda: experiments

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


def _sample_config_body() -> dict[str, Any]:
    return {
        "name": "rag-faq",
        "description": "demo",
        "prompt": {"system": "You are helpful."},
        "model": {"model_id": "gpt-demo"},
        "retrieval": {"top_k": 5},
    }


async def _project_and_dataset(client: AsyncClient) -> tuple[str, str]:
    project = await client.post("/api/v1/projects", json={"name": "Exp AppConfig"})
    assert project.status_code == 201
    project_id = project.json()["id"]
    dataset = await client.post(
        f"/api/v1/projects/{project_id}/datasets",
        json={"name": "ds-1"},
    )
    assert dataset.status_code == 201
    return project_id, dataset.json()["id"]


@pytest.mark.asyncio
async def test_create_experiment_with_app_config_alias_binds_snapshot(
    client: AsyncClient,
) -> None:
    project_id, dataset_id = await _project_and_dataset(client)

    created = await client.post(
        f"/api/v1/projects/{project_id}/app-configs",
        json=_sample_config_body(),
    )
    assert created.status_code == 201
    config_id = created.json()["id"]

    alias = await client.put(
        f"/api/v1/projects/{project_id}/app-config-aliases/candidate",
        json={"app_config_id": config_id},
    )
    assert alias.status_code == 200

    exp = await client.post(
        f"/api/v1/projects/{project_id}/experiments",
        json={
            "name": "run-1",
            "dataset_id": dataset_id,
            "app_config_alias": "candidate",
            "model_config": {"ignored": True},
        },
    )
    assert exp.status_code == 201, exp.text
    body = exp.json()
    assert body["app_config_id"] == config_id
    mc = body["model_config"]
    assert mc["prompt"] == {"system": "You are helpful."}
    assert mc["model"] == {"model_id": "gpt-demo"}
    assert mc["retrieval"] == {"top_k": 5}
    assert "content_hash" in mc
    assert mc["app_config_id"] == config_id


@pytest.mark.asyncio
async def test_create_experiment_rejects_both_app_config_id_and_alias(
    client: AsyncClient,
) -> None:
    project_id, dataset_id = await _project_and_dataset(client)
    config_id = uuid.uuid4()
    resp = await client.post(
        f"/api/v1/projects/{project_id}/experiments",
        json={
            "name": "run-both",
            "dataset_id": dataset_id,
            "app_config_id": str(config_id),
            "app_config_alias": "candidate",
        },
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_create_experiment_unknown_alias_returns_400(client: AsyncClient) -> None:
    project_id, dataset_id = await _project_and_dataset(client)
    resp = await client.post(
        f"/api/v1/projects/{project_id}/experiments",
        json={
            "name": "run-unknown",
            "dataset_id": dataset_id,
            "app_config_alias": "missing",
        },
    )
    assert resp.status_code == 400
    assert "Unknown app_config_alias" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_create_experiment_with_app_config_id_ignores_model_config(
    client: AsyncClient,
) -> None:
    project_id, dataset_id = await _project_and_dataset(client)
    created = await client.post(
        f"/api/v1/projects/{project_id}/app-configs",
        json=_sample_config_body(),
    )
    config_id = created.json()["id"]

    exp = await client.post(
        f"/api/v1/projects/{project_id}/experiments",
        json={
            "name": "run-id",
            "dataset_id": dataset_id,
            "app_config_id": config_id,
            "model_config": {"custom": "ignored"},
        },
    )
    assert exp.status_code == 201, exp.text
    body = exp.json()
    assert body["app_config_id"] == config_id
    assert body["model_config"]["prompt"] == {"system": "You are helpful."}
    assert "custom" not in body["model_config"]


@pytest.mark.asyncio
async def test_create_experiment_without_app_config_keeps_free_form_model_config(
    client: AsyncClient,
) -> None:
    project_id, dataset_id = await _project_and_dataset(client)
    exp = await client.post(
        f"/api/v1/projects/{project_id}/experiments",
        json={
            "name": "run-free",
            "dataset_id": dataset_id,
            "model_config": {"temperature": 0.2, "model_id": "local"},
        },
    )
    assert exp.status_code == 201, exp.text
    body = exp.json()
    assert body.get("app_config_id") is None
    assert body["model_config"] == {"temperature": 0.2, "model_id": "local"}


@pytest.mark.asyncio
async def test_create_experiment_missing_app_config_id_returns_404(
    client: AsyncClient,
) -> None:
    project_id, dataset_id = await _project_and_dataset(client)
    missing = uuid.uuid4()
    resp = await client.post(
        f"/api/v1/projects/{project_id}/experiments",
        json={
            "name": "run-missing",
            "dataset_id": dataset_id,
            "app_config_id": str(missing),
        },
    )
    assert resp.status_code == 404
