from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from aiobs.api.deps import (
    get_dataset_repository,
    get_evaluation_run_repository,
    get_evaluator_repository,
    get_experiment_item_output_repository,
    get_experiment_repository,
    get_metrics_set_repository,
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

    async def upsert(self, output: ExperimentItemOutput) -> ExperimentItemOutput:
        self._outputs[(output.experiment_id, output.dataset_item_id)] = output
        return output

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
async def release_env() -> AsyncIterator[tuple[AsyncClient, InMemoryEvaluationRunRepository]]:
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


async def _seed_quality(
    client: AsyncClient, *, actual_output: str = "hello"
) -> tuple[str, str, str, str]:
    project = await client.post("/api/v1/projects", json={"name": "Release Demo"})
    assert project.status_code == 201
    project_id = project.json()["id"]

    dataset = await client.post(
        f"/api/v1/projects/{project_id}/datasets",
        json={"name": "support-v1", "task_type": "classification"},
    )
    dataset_id = dataset.json()["id"]
    item = await client.post(
        f"/api/v1/datasets/{dataset_id}/items",
        json={
            "input": "hi",
            "expected_output": "hello",
            "actual_output": actual_output,
        },
    )
    assert item.status_code == 201

    evaluator = await client.post(
        f"/api/v1/projects/{project_id}/evaluators",
        json={
            "name": "quality",
            "type": "deterministic",
            "config": {"kind": "exact_match"},
        },
    )
    assert evaluator.status_code == 201
    return project_id, dataset_id, evaluator.json()["id"], item.json()["id"]


@pytest.mark.asyncio
async def test_release_check_passes_quality_min(
    release_env: tuple[AsyncClient, InMemoryEvaluationRunRepository],
) -> None:
    client, _ = release_env
    project_id, dataset_id, evaluator_id, _item_id = await _seed_quality(client)

    experiment = await client.post(
        f"/api/v1/projects/{project_id}/experiments",
        json={"name": "cand", "dataset_id": dataset_id},
    )
    experiment_id = experiment.json()["id"]
    evaluated = await client.post(
        f"/api/v1/experiments/{experiment_id}/evaluate",
        json={"evaluator_ids": [evaluator_id]},
    )
    assert evaluated.status_code == 200

    response = await client.post(
        f"/api/v1/projects/{project_id}/release-check",
        json={
            "experiment_id": experiment_id,
            "policy": {"quality": {"min": 0.85}},
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "passed"
    assert body["checks"][0]["metric"] == "quality.min"
    assert body["checks"][0]["status"] == "passed"


@pytest.mark.asyncio
async def test_release_check_fails_quality_and_regression(
    release_env: tuple[AsyncClient, InMemoryEvaluationRunRepository],
) -> None:
    client, _ = release_env
    project_id, dataset_id, evaluator_id, item_id = await _seed_quality(client)

    second_item_id = item_id
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

    put = await client.put(
        f"/api/v1/experiments/{candidate_id}/outputs",
        json={"items": [{"dataset_item_id": second_item_id, "actual_output": "nope"}]},
    )
    assert put.status_code == 200

    for experiment_id in (baseline_id, candidate_id):
        evaluated = await client.post(
            f"/api/v1/experiments/{experiment_id}/evaluate",
            json={"evaluator_ids": [evaluator_id]},
        )
        assert evaluated.status_code == 200

    response = await client.post(
        f"/api/v1/projects/{project_id}/release-check",
        json={
            "experiment_id": candidate_id,
            "policy": {
                "quality": {"min": 0.85},
                "regression": {"max_delta": -0.03},
            },
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "failed"
    assert body["baseline_experiment_id"] == baseline_id
    by_metric = {c["metric"]: c for c in body["checks"]}
    assert by_metric["quality.min"]["status"] == "failed"
    assert by_metric["regression.quality.mean_score"]["status"] == "failed"


@pytest.mark.asyncio
async def test_release_check_missing_baseline_and_invalid_policy(
    release_env: tuple[AsyncClient, InMemoryEvaluationRunRepository],
) -> None:
    client, _ = release_env
    project_id, dataset_id, evaluator_id, _item_id = await _seed_quality(client)
    experiment = await client.post(
        f"/api/v1/projects/{project_id}/experiments",
        json={"name": "cand", "dataset_id": dataset_id},
    )
    experiment_id = experiment.json()["id"]
    await client.post(
        f"/api/v1/experiments/{experiment_id}/evaluate",
        json={"evaluator_ids": [evaluator_id]},
    )

    missing_baseline = await client.post(
        f"/api/v1/projects/{project_id}/release-check",
        json={
            "experiment_id": experiment_id,
            "policy": {"regression": {"max_delta": -0.03}},
        },
    )
    assert missing_baseline.status_code == 400

    invalid = await client.post(
        f"/api/v1/projects/{project_id}/release-check",
        json={
            "experiment_id": experiment_id,
            "policy": {"quality": {"min": 0.8, "extra": 1}},
        },
    )
    assert invalid.status_code == 400


@pytest.mark.asyncio
async def test_release_check_latency_unavailable_without_metadata(
    release_env: tuple[AsyncClient, InMemoryEvaluationRunRepository],
) -> None:
    client, runs = release_env
    project_id, dataset_id, _, _item_id = await _seed_quality(client)
    experiment = await client.post(
        f"/api/v1/projects/{project_id}/experiments",
        json={"name": "cand", "dataset_id": dataset_id},
    )
    experiment_id = uuid.UUID(experiment.json()["id"])

    evaluator_id = uuid.uuid4()
    run = EvaluationRun(
        id=uuid.uuid4(),
        experiment_id=experiment_id,
        evaluator_id=evaluator_id,
        status="PASSED",
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        metadata={"evaluator_name": "latency"},
    )
    await runs.add_run(run)
    await runs.add_result(
        EvaluationResultRecord.create(
            run.id,
            uuid.uuid4(),
            score=1.0,
            label="PASS",
            metadata={},
        )
    )

    response = await client.post(
        f"/api/v1/projects/{project_id}/release-check",
        json={
            "experiment_id": str(experiment_id),
            "policy": {"latency": {"p95_max_ms": 2000}},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["checks"][0]["status"] == "unavailable"


@pytest.mark.asyncio
async def test_release_check_latency_pass_with_seeded_metadata(
    release_env: tuple[AsyncClient, InMemoryEvaluationRunRepository],
) -> None:
    client, runs = release_env
    project_id, dataset_id, _, _item_id = await _seed_quality(client)
    experiment = await client.post(
        f"/api/v1/projects/{project_id}/experiments",
        json={"name": "cand", "dataset_id": dataset_id},
    )
    experiment_id = uuid.UUID(experiment.json()["id"])

    run = EvaluationRun(
        id=uuid.uuid4(),
        experiment_id=experiment_id,
        evaluator_id=uuid.uuid4(),
        status="PASSED",
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        metadata={"evaluator_name": "latency"},
    )
    await runs.add_run(run)
    for latency_ms in (100.0, 200.0, 300.0):
        await runs.add_result(
            EvaluationResultRecord.create(
                run.id,
                uuid.uuid4(),
                score=1.0,
                label="PASS",
                metadata={"latency_ms": latency_ms},
            )
        )

    response = await client.post(
        f"/api/v1/projects/{project_id}/release-check",
        json={
            "experiment_id": str(experiment_id),
            "policy": {"latency": {"p95_max_ms": 2000}},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "passed"
    assert body["checks"][0]["metric"] == "latency.p95"
    assert body["checks"][0]["actual"] == 300.0
