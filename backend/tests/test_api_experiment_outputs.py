from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from aiobs.api.deps import (
    get_dataset_repository,
    get_evaluation_run_repository,
    get_evaluator_repository,
    get_experiment_item_output_repository,
    get_experiment_repository,
    get_project_repository,
    get_trace_repository,
)
from aiobs.domain.dataset import Dataset, DatasetItem
from aiobs.domain.evaluation import EvaluationResultRecord, EvaluationRun
from aiobs.domain.evaluator import Evaluator
from aiobs.domain.experiment import Experiment
from aiobs.domain.experiment_output import ExperimentItemOutput
from aiobs.domain.project import Project
from aiobs.domain.trace import Trace
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
        return list(self._projects.values())


class InMemoryTraceRepository:
    def __init__(self) -> None:
        self._traces: dict[tuple[uuid.UUID, str], Trace] = {}

    async def upsert(self, trace: Trace) -> Trace:
        self._traces[(trace.project_id, trace.trace_id)] = trace
        return trace

    async def get_by_trace_id(self, project_id: uuid.UUID, trace_id: str) -> Trace | None:
        return self._traces.get((project_id, trace_id))

    async def list_by_project(self, project_id: uuid.UUID, **kwargs: Any) -> list[Trace]:
        return [t for (pid, _), t in self._traces.items() if pid == project_id]


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
            if d.project_id == project_id
            and (task_type is None or d.task_type == task_type)
        ]

    async def add_item(self, item: DatasetItem) -> DatasetItem:
        self._items[item.id] = item
        return item

    async def list_items(self, dataset_id: uuid.UUID) -> list[DatasetItem]:
        return [i for i in self._items.values() if i.dataset_id == dataset_id]

    async def get_item(self, item_id: uuid.UUID) -> DatasetItem | None:
        return self._items.get(item_id)


class InMemoryEvaluatorRepository:
    def __init__(self) -> None:
        self._items: dict[uuid.UUID, Evaluator] = {}

    async def add(self, evaluator: Evaluator) -> Evaluator:
        self._items[evaluator.id] = evaluator
        return evaluator

    async def get_by_id(self, evaluator_id: uuid.UUID) -> Evaluator | None:
        return self._items.get(evaluator_id)

    async def list_by_project(self, project_id: uuid.UUID) -> list[Evaluator]:
        return [e for e in self._items.values() if e.project_id == project_id]

    async def get_by_ids(self, evaluator_ids: list[uuid.UUID]) -> list[Evaluator]:
        return [self._items[i] for i in evaluator_ids if i in self._items]


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


class InMemoryEvaluationRunRepository:
    def __init__(self) -> None:
        self._runs: dict[uuid.UUID, EvaluationRun] = {}
        self._results: dict[uuid.UUID, EvaluationResultRecord] = {}

    async def add_run(self, run: EvaluationRun) -> EvaluationRun:
        self._runs[run.id] = run
        return run

    async def update_run(self, run: EvaluationRun) -> EvaluationRun:
        self._runs[run.id] = run
        return run

    async def get_run(self, run_id: uuid.UUID) -> EvaluationRun | None:
        return self._runs.get(run_id)

    async def list_runs_by_experiment(self, experiment_id: uuid.UUID) -> list[EvaluationRun]:
        return [r for r in self._runs.values() if r.experiment_id == experiment_id]

    async def add_result(self, result: EvaluationResultRecord) -> EvaluationResultRecord:
        self._results[result.id] = result
        return result

    async def list_results(self, run_id: uuid.UUID) -> list[EvaluationResultRecord]:
        return [r for r in self._results.values() if r.run_id == run_id]

    async def add_results(
        self, results: list[EvaluationResultRecord]
    ) -> list[EvaluationResultRecord]:
        for r in results:
            self._results[r.id] = r
        return results


class InMemoryExperimentItemOutputRepository:
    def __init__(self) -> None:
        self._outputs: dict[tuple[uuid.UUID, uuid.UUID], ExperimentItemOutput] = {}

    async def get(
        self, experiment_id: uuid.UUID, dataset_item_id: uuid.UUID
    ) -> ExperimentItemOutput | None:
        return self._outputs.get((experiment_id, dataset_item_id))

    async def upsert_many(
        self, outputs: list[ExperimentItemOutput]
    ) -> list[ExperimentItemOutput]:
        for output in outputs:
            self._outputs[(output.experiment_id, output.dataset_item_id)] = output
        return outputs

    async def list_by_experiment(
        self, experiment_id: uuid.UUID
    ) -> list[ExperimentItemOutput]:
        return sorted(
            (o for (eid, _), o in self._outputs.items() if eid == experiment_id),
            key=lambda o: o.dataset_item_id,
        )


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    import os

    from aiobs.config import get_settings

    os.environ["CONTENT_CAPTURE_ENABLED"] = "true"
    get_settings.cache_clear()

    projects = InMemoryProjectRepository()
    traces = InMemoryTraceRepository()
    datasets = InMemoryDatasetRepository()
    evaluators = InMemoryEvaluatorRepository()
    experiments = InMemoryExperimentRepository()
    runs = InMemoryEvaluationRunRepository()
    outputs = InMemoryExperimentItemOutputRepository()

    app = create_app()
    app.dependency_overrides[get_project_repository] = lambda: projects
    app.dependency_overrides[get_trace_repository] = lambda: traces
    app.dependency_overrides[get_dataset_repository] = lambda: datasets
    app.dependency_overrides[get_evaluator_repository] = lambda: evaluators
    app.dependency_overrides[get_experiment_repository] = lambda: experiments
    app.dependency_overrides[get_evaluation_run_repository] = lambda: runs
    app.dependency_overrides[get_experiment_item_output_repository] = lambda: outputs

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
    os.environ.pop("CONTENT_CAPTURE_ENABLED", None)
    get_settings.cache_clear()


async def _seed_experiment_with_item(client: AsyncClient) -> tuple[str, str]:
    project = await client.post("/api/v1/projects", json={"name": "Outputs Demo"})
    assert project.status_code == 201
    project_id = project.json()["id"]

    dataset = await client.post(
        f"/api/v1/projects/{project_id}/datasets",
        json={"name": "ds-outputs"},
    )
    assert dataset.status_code == 201
    dataset_id = dataset.json()["id"]

    item = await client.post(
        f"/api/v1/datasets/{dataset_id}/items",
        json={"input": "question", "expected_output": "answer"},
    )
    assert item.status_code == 201
    item_id = item.json()["id"]

    experiment = await client.post(
        f"/api/v1/projects/{project_id}/experiments",
        json={"name": "exp-outputs", "dataset_id": dataset_id},
    )
    assert experiment.status_code == 201
    return experiment.json()["id"], item_id


@pytest.mark.asyncio
async def test_put_then_get_experiment_outputs(client: AsyncClient) -> None:
    experiment_id, item_id = await _seed_experiment_with_item(client)

    put = await client.put(
        f"/api/v1/experiments/{experiment_id}/outputs",
        json={
            "items": [
                {
                    "dataset_item_id": item_id,
                    "actual_output": "model answer",
                    "context": {"doc": 1},
                    "metadata": {"source": "test"},
                }
            ]
        },
    )
    assert put.status_code == 200, put.text
    body = put.json()
    assert body["upserted"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["experiment_id"] == experiment_id
    assert body["items"][0]["dataset_item_id"] == item_id
    assert body["items"][0]["actual_output"] == "model answer"
    assert body["items"][0]["context"] == {"doc": 1}
    assert body["items"][0]["metadata"] == {"source": "test"}

    listed = await client.get(f"/api/v1/experiments/{experiment_id}/outputs")
    assert listed.status_code == 200, listed.text
    rows = listed.json()
    assert len(rows) == 1
    assert rows[0]["dataset_item_id"] == item_id
    assert rows[0]["actual_output"] == "model answer"


@pytest.mark.asyncio
async def test_put_foreign_dataset_item_returns_400(client: AsyncClient) -> None:
    experiment_id, item_id = await _seed_experiment_with_item(client)
    foreign_item_id = str(uuid.uuid4())
    assert foreign_item_id != item_id

    response = await client.put(
        f"/api/v1/experiments/{experiment_id}/outputs",
        json={
            "items": [
                {
                    "dataset_item_id": foreign_item_id,
                    "actual_output": "nope",
                }
            ]
        },
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_put_omit_context_preserves_null_clears(client: AsyncClient) -> None:
    experiment_id, item_id = await _seed_experiment_with_item(client)

    first = await client.put(
        f"/api/v1/experiments/{experiment_id}/outputs",
        json={
            "items": [
                {
                    "dataset_item_id": item_id,
                    "actual_output": "v1",
                    "context": {"keep": True},
                }
            ]
        },
    )
    assert first.status_code == 200

    omit = await client.put(
        f"/api/v1/experiments/{experiment_id}/outputs",
        json={
            "items": [
                {
                    "dataset_item_id": item_id,
                    "actual_output": "v2",
                }
            ]
        },
    )
    assert omit.status_code == 200
    assert omit.json()["items"][0]["actual_output"] == "v2"
    assert omit.json()["items"][0]["context"] == {"keep": True}

    clear = await client.put(
        f"/api/v1/experiments/{experiment_id}/outputs",
        json={
            "items": [
                {
                    "dataset_item_id": item_id,
                    "context": None,
                }
            ]
        },
    )
    assert clear.status_code == 200
    assert clear.json()["items"][0]["context"] is None
    assert clear.json()["items"][0]["actual_output"] == "v2"


@pytest.mark.asyncio
async def test_get_outputs_missing_experiment_404(client: AsyncClient) -> None:
    missing = uuid.uuid4()
    response = await client.get(f"/api/v1/experiments/{missing}/outputs")
    assert response.status_code == 404
