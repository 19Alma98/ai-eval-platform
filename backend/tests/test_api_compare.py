from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx2 import ASGITransport, AsyncClient

from aiobs_server.api.deps import (
    get_dataset_repository,
    get_evaluation_run_repository,
    get_evaluator_repository,
    get_experiment_item_output_repository,
    get_experiment_repository,
    get_metrics_set_repository,
    get_project_repository,
    get_trace_repository,
)
from aiobs_server.domain.dataset import Dataset, DatasetItem
from aiobs_server.domain.evaluation import EvaluationResultRecord, EvaluationRun
from aiobs_server.domain.evaluator import Evaluator
from aiobs_server.domain.experiment import Experiment
from aiobs_server.domain.experiment_output import ExperimentItemOutput
from aiobs_server.domain.project import Project
from aiobs_server.domain.trace import Trace
from aiobs_server.main import create_app
from tests.support.repositories import InMemoryMetricsSetRepository


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
            if d.project_id == project_id and (task_type is None or d.task_type == task_type)
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

    async def count_by_metrics_set_id(self, metrics_set_id: uuid.UUID) -> int:
        return sum(1 for e in self._items.values() if e.metrics_set_id == metrics_set_id)


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

    async def upsert_many(self, outputs: list[ExperimentItemOutput]) -> list[ExperimentItemOutput]:
        for output in outputs:
            self._outputs[(output.experiment_id, output.dataset_item_id)] = output
        return outputs

    async def list_by_experiment(self, experiment_id: uuid.UUID) -> list[ExperimentItemOutput]:
        return sorted(
            (o for (eid, _), o in self._outputs.items() if eid == experiment_id),
            key=lambda o: o.dataset_item_id,
        )


@pytest.fixture
async def compare_env() -> AsyncIterator[tuple[AsyncClient, InMemoryEvaluationRunRepository]]:
    import os

    from aiobs_server.config import get_settings

    os.environ["CONTENT_CAPTURE_ENABLED"] = "true"
    get_settings.cache_clear()

    projects = InMemoryProjectRepository()
    traces = InMemoryTraceRepository()
    datasets = InMemoryDatasetRepository()
    evaluators = InMemoryEvaluatorRepository()
    experiments = InMemoryExperimentRepository()
    runs = InMemoryEvaluationRunRepository()
    outputs = InMemoryExperimentItemOutputRepository()
    metrics_sets = InMemoryMetricsSetRepository()

    app = create_app()
    app.dependency_overrides[get_project_repository] = lambda: projects
    app.dependency_overrides[get_trace_repository] = lambda: traces
    app.dependency_overrides[get_dataset_repository] = lambda: datasets
    app.dependency_overrides[get_evaluator_repository] = lambda: evaluators
    app.dependency_overrides[get_experiment_repository] = lambda: experiments
    app.dependency_overrides[get_evaluation_run_repository] = lambda: runs
    app.dependency_overrides[get_experiment_item_output_repository] = lambda: outputs
    app.dependency_overrides[get_metrics_set_repository] = lambda: metrics_sets

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, runs

    app.dependency_overrides.clear()
    os.environ.pop("CONTENT_CAPTURE_ENABLED", None)
    get_settings.cache_clear()


@pytest.fixture
async def client(
    compare_env: tuple[AsyncClient, InMemoryEvaluationRunRepository],
) -> AsyncIterator[AsyncClient]:
    yield compare_env[0]


async def _seed_dataset_and_evaluator(client: AsyncClient) -> tuple[str, str, str]:
    project = await client.post("/api/v1/projects", json={"name": "Compare Demo"})
    assert project.status_code == 201
    project_id = project.json()["id"]

    dataset = await client.post(
        f"/api/v1/projects/{project_id}/datasets",
        json={"name": "support-v1", "task_type": "classification"},
    )
    assert dataset.status_code == 201
    dataset_id = dataset.json()["id"]

    item = await client.post(
        f"/api/v1/datasets/{dataset_id}/items",
        json={
            "input": "hi",
            "expected_output": "hello",
            "actual_output": "hello",
        },
    )
    assert item.status_code == 201

    evaluator = await client.post(
        f"/api/v1/projects/{project_id}/evaluators",
        json={
            "name": "exact",
            "type": "deterministic",
            "config": {"kind": "exact_match"},
        },
    )
    assert evaluator.status_code == 201
    return project_id, dataset_id, evaluator.json()["id"]


@pytest.mark.asyncio
async def test_summary_and_compare_experiments(client: AsyncClient) -> None:
    project_id, dataset_id, evaluator_id = await _seed_dataset_and_evaluator(client)

    second_item_id = None
    for idx in range(2, 6):
        item = await client.post(
            f"/api/v1/datasets/{dataset_id}/items",
            json={
                "input": f"hi{idx}",
                "expected_output": "hello",
                "actual_output": "hello",
            },
        )
        assert item.status_code == 201
        if idx == 2:
            second_item_id = item.json()["id"]
    assert second_item_id is not None

    baseline = await client.post(
        f"/api/v1/projects/{project_id}/experiments",
        json={"name": "baseline", "dataset_id": dataset_id},
    )
    assert baseline.status_code == 201
    baseline_id = baseline.json()["id"]

    candidate = await client.post(
        f"/api/v1/projects/{project_id}/experiments",
        json={
            "name": "candidate",
            "dataset_id": dataset_id,
            "baseline_experiment_id": baseline_id,
        },
    )
    assert candidate.status_code == 201
    candidate_id = candidate.json()["id"]

    put = await client.put(
        f"/api/v1/experiments/{candidate_id}/outputs",
        json={
            "items": [
                {"dataset_item_id": second_item_id, "actual_output": "nope"},
            ]
        },
    )
    assert put.status_code == 200, put.text

    for experiment_id in (baseline_id, candidate_id):
        evaluated = await client.post(
            f"/api/v1/experiments/{experiment_id}/evaluate",
            json={"evaluator_ids": [evaluator_id]},
        )
        assert evaluated.status_code == 200, evaluated.text

    summary = await client.get(f"/api/v1/experiments/{baseline_id}/summary")
    assert summary.status_code == 200, summary.text
    body = summary.json()
    assert body["experiment_id"] == baseline_id
    assert len(body["evaluators"]) == 1
    assert body["evaluators"][0]["mean_score"] == 1.0
    assert body["evaluators"][0]["pass_rate"] == 1.0
    assert body["evaluators"][0]["evaluator_name"] == "exact"

    compare = await client.get(f"/api/v1/experiments/{candidate_id}/compare/{baseline_id}")
    assert compare.status_code == 200, compare.text
    cmp = compare.json()
    assert cmp["experiment_id"] == candidate_id
    assert cmp["baseline_experiment_id"] == baseline_id
    assert len(cmp["metrics"]) == 2
    assert {m["metric"] for m in cmp["metrics"]} == {"mean_score", "pass_rate"}
    assert all(m["status"] == "regression" for m in cmp["metrics"])
    assert len(cmp["regressions"]) == 2
    assert cmp["improved"] == []
    assert cmp["unchanged"] == []
    assert len(cmp["candidate_runs"]) == 1
    assert len(cmp["baseline_runs"]) == 1
    assert cmp["candidate_runs"][0]["evaluator_id"] == evaluator_id
    assert cmp["baseline_runs"][0]["evaluator_id"] == evaluator_id
    assert "run_id" in cmp["candidate_runs"][0]
    assert "metadata" in cmp["candidate_runs"][0]


@pytest.mark.asyncio
async def test_compare_exposes_run_judge_warnings(
    compare_env: tuple[AsyncClient, InMemoryEvaluationRunRepository],
) -> None:
    client, runs = compare_env
    project_id, dataset_id, evaluator_id = await _seed_dataset_and_evaluator(client)

    for idx in range(2, 6):
        item = await client.post(
            f"/api/v1/datasets/{dataset_id}/items",
            json={
                "input": f"hi{idx}",
                "expected_output": "hello",
                "actual_output": "hello",
            },
        )
        assert item.status_code == 201

    baseline = await client.post(
        f"/api/v1/projects/{project_id}/experiments",
        json={"name": "baseline", "dataset_id": dataset_id},
    )
    baseline_id = baseline.json()["id"]
    candidate = await client.post(
        f"/api/v1/projects/{project_id}/experiments",
        json={
            "name": "candidate",
            "dataset_id": dataset_id,
            "baseline_experiment_id": baseline_id,
        },
    )
    candidate_id = candidate.json()["id"]

    for experiment_id in (baseline_id, candidate_id):
        evaluated = await client.post(
            f"/api/v1/experiments/{experiment_id}/evaluate",
            json={"evaluator_ids": [evaluator_id]},
        )
        assert evaluated.status_code == 200, evaluated.text

    cand_run = next(r for r in runs._runs.values() if r.experiment_id == uuid.UUID(candidate_id))
    updated = cand_run.with_status(
        cand_run.status,
        metadata={
            **cand_run.metadata,
            "warnings": ["judge_model_unsuitable"],
            "warning_detail": {
                "model": "tiny",
                "method": "claims",
                "failure_rate": 0.3,
                "message": "Judge model tiny returned unusable output.",
            },
        },
    )
    await runs.update_run(updated)

    compare = await client.get(f"/api/v1/experiments/{candidate_id}/compare/{baseline_id}")
    assert compare.status_code == 200, compare.text
    cmp = compare.json()
    assert cmp["candidate_runs"][0]["metadata"]["warnings"] == ["judge_model_unsuitable"]
    assert (
        cmp["candidate_runs"][0]["metadata"]["warning_detail"]["message"]
        == "Judge model tiny returned unusable output."
    )
    assert "warnings" not in cmp["baseline_runs"][0]["metadata"]


@pytest.mark.asyncio
async def test_compare_missing_baseline_404(client: AsyncClient) -> None:
    project_id, dataset_id, evaluator_id = await _seed_dataset_and_evaluator(client)
    experiment = await client.post(
        f"/api/v1/projects/{project_id}/experiments",
        json={"name": "only", "dataset_id": dataset_id},
    )
    experiment_id = experiment.json()["id"]
    await client.post(
        f"/api/v1/experiments/{experiment_id}/evaluate",
        json={"evaluator_ids": [evaluator_id]},
    )
    missing = uuid.uuid4()
    response = await client.get(f"/api/v1/experiments/{experiment_id}/compare/{missing}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_compare_rejects_different_dataset(client: AsyncClient) -> None:
    project_id, dataset_id, evaluator_id = await _seed_dataset_and_evaluator(client)
    other_dataset = await client.post(
        f"/api/v1/projects/{project_id}/datasets",
        json={"name": "other-set", "task_type": "classification"},
    )
    assert other_dataset.status_code == 201
    other_dataset_id = other_dataset.json()["id"]
    await client.post(
        f"/api/v1/datasets/{other_dataset_id}/items",
        json={
            "input": "x",
            "expected_output": "y",
            "actual_output": "y",
        },
    )

    baseline = await client.post(
        f"/api/v1/projects/{project_id}/experiments",
        json={"name": "base", "dataset_id": dataset_id},
    )
    baseline_id = baseline.json()["id"]
    candidate = await client.post(
        f"/api/v1/projects/{project_id}/experiments",
        json={"name": "cand", "dataset_id": other_dataset_id},
    )
    candidate_id = candidate.json()["id"]

    for experiment_id in (baseline_id, candidate_id):
        evaluated = await client.post(
            f"/api/v1/experiments/{experiment_id}/evaluate",
            json={"evaluator_ids": [evaluator_id]},
        )
        assert evaluated.status_code == 200, evaluated.text

    response = await client.get(f"/api/v1/experiments/{candidate_id}/compare/{baseline_id}")
    assert response.status_code == 400
    assert response.json()["detail"] == "Runs must share the same dataset (test set version)"


@pytest.mark.asyncio
async def test_summary_without_runs_returns_empty_evaluators(client: AsyncClient) -> None:
    project_id, dataset_id, _evaluator_id = await _seed_dataset_and_evaluator(client)
    experiment = await client.post(
        f"/api/v1/projects/{project_id}/experiments",
        json={"name": "empty", "dataset_id": dataset_id},
    )
    experiment_id = experiment.json()["id"]
    response = await client.get(f"/api/v1/experiments/{experiment_id}/summary")
    assert response.status_code == 200
    body = response.json()
    assert body["experiment_id"] == experiment_id
    assert body["evaluators"] == []
