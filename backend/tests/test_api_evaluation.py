from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from aiobs.api.deps import (
    get_app_config_repository,
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
from support.repositories import InMemoryAppConfigRepository, InMemoryMetricsSetRepository


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
        for existing in self._datasets.values():
            if (
                existing.project_id == dataset.project_id
                and existing.name == dataset.name
                and existing.version == dataset.version
            ):
                raise Exception("unique constraint")
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
    metrics_sets = InMemoryMetricsSetRepository()
    app_configs = InMemoryAppConfigRepository()

    app = create_app()
    app.dependency_overrides[get_project_repository] = lambda: projects
    app.dependency_overrides[get_metrics_set_repository] = lambda: metrics_sets
    app.dependency_overrides[get_trace_repository] = lambda: traces
    app.dependency_overrides[get_dataset_repository] = lambda: datasets
    app.dependency_overrides[get_evaluator_repository] = lambda: evaluators
    app.dependency_overrides[get_experiment_repository] = lambda: experiments
    app.dependency_overrides[get_evaluation_run_repository] = lambda: runs
    app.dependency_overrides[get_experiment_item_output_repository] = lambda: outputs
    app.dependency_overrides[get_app_config_repository] = lambda: app_configs

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
    os.environ.pop("CONTENT_CAPTURE_ENABLED", None)
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_dataset_item_evaluate_flow(client: AsyncClient) -> None:
    project = await client.post("/api/v1/projects", json={"name": "Eval Demo"})
    assert project.status_code == 201
    project_id = project.json()["id"]

    dataset = await client.post(
        f"/api/v1/projects/{project_id}/datasets",
        json={"name": "support-v1", "description": "demo", "task_type": "classification"},
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
    evaluator_id = evaluator.json()["id"]

    experiment = await client.post(
        f"/api/v1/projects/{project_id}/experiments",
        json={"name": "run-1", "dataset_id": dataset_id, "model_config": {"model": "demo"}},
    )
    assert experiment.status_code == 201, experiment.text
    experiment_id = experiment.json()["id"]
    assert experiment.json()["model_config"] == {"model": "demo"}

    evaluated = await client.post(
        f"/api/v1/experiments/{experiment_id}/evaluate",
        json={"evaluator_ids": [evaluator_id]},
    )
    assert evaluated.status_code == 200, evaluated.text
    body = evaluated.json()
    assert body["experiment"]["status"] == "completed"
    assert len(body["runs"]) == 1
    assert body["runs"][0]["status"] == "PASSED"
    assert body["runs"][0]["results"][0]["score"] == 1.0

    runs = await client.get(f"/api/v1/experiments/{experiment_id}/runs")
    assert runs.status_code == 200
    assert len(runs.json()) == 1

    run_id = body["runs"][0]["id"]
    detail = await client.get(f"/api/v1/evaluation-runs/{run_id}")
    assert detail.status_code == 200
    assert len(detail.json()["results"]) == 1


@pytest.mark.asyncio
async def test_evaluate_uses_experiment_output_not_legacy_actual(
    client: AsyncClient,
) -> None:
    project = await client.post("/api/v1/projects", json={"name": "Exp Output Eval"})
    project_id = project.json()["id"]

    dataset = await client.post(
        f"/api/v1/projects/{project_id}/datasets",
        json={"name": "merged-outputs", "task_type": "classification"},
    )
    dataset_id = dataset.json()["id"]

    item = await client.post(
        f"/api/v1/datasets/{dataset_id}/items",
        json={
            "input": "q",
            "expected_output": "candidate",
            "actual_output": "legacy",
        },
    )
    assert item.status_code == 201
    item_id = item.json()["id"]

    evaluator = await client.post(
        f"/api/v1/projects/{project_id}/evaluators",
        json={
            "name": "exact",
            "type": "deterministic",
            "config": {"kind": "exact_match"},
        },
    )
    evaluator_id = evaluator.json()["id"]

    experiment = await client.post(
        f"/api/v1/projects/{project_id}/experiments",
        json={"name": "with-outputs", "dataset_id": dataset_id},
    )
    experiment_id = experiment.json()["id"]

    put = await client.put(
        f"/api/v1/experiments/{experiment_id}/outputs",
        json={
            "items": [
                {"dataset_item_id": item_id, "actual_output": "candidate"},
            ]
        },
    )
    assert put.status_code == 200, put.text

    evaluated = await client.post(
        f"/api/v1/experiments/{experiment_id}/evaluate",
        json={"evaluator_ids": [evaluator_id]},
    )
    assert evaluated.status_code == 200, evaluated.text
    assert evaluated.json()["runs"][0]["results"][0]["score"] == 1.0


@pytest.mark.asyncio
async def test_from_trace_item(client: AsyncClient) -> None:
    project = await client.post("/api/v1/projects", json={"name": "From Trace"})
    project_id = project.json()["id"]

    start = datetime(2024, 1, 1, tzinfo=UTC).isoformat()
    end = datetime(2024, 1, 1, 0, 0, 2, tzinfo=UTC).isoformat()
    create_trace = await client.post(
        f"/api/v1/projects/{project_id}/traces",
        json={
            "trace_id": "ab" * 16,
            "name": "chat",
            "status": "ok",
            "start_time": start,
            "end_time": end,
            "input": {"q": "hi"},
            "output": {"a": "hello"},
            "spans": [
                {
                    "span_id": "cd" * 8,
                    "name": "llm",
                    "kind": "LLM",
                    "start_time": start,
                    "end_time": end,
                    "status": "ok",
                    "attributes": {"gen_ai.usage.total_tokens": 10},
                }
            ],
        },
    )
    assert create_trace.status_code in {200, 201}, create_trace.text

    dataset = await client.post(
        f"/api/v1/projects/{project_id}/datasets",
        json={"name": "from-trace", "task_type": "classification"},
    )
    dataset_id = dataset.json()["id"]

    item = await client.post(
        f"/api/v1/datasets/{dataset_id}/items/from-trace",
        json={"trace_id": "ab" * 16, "expected_output": {"a": "hello"}},
    )
    assert item.status_code == 201, item.text
    body = item.json()
    assert body["input"] == {"q": "hi"}
    assert body["actual_output"] == {"a": "hello"}
    assert body["context"]["latency_ms"] == 2000.0
    assert body["context"]["total_tokens"] == 10


_DEFAULT_PACK_KINDS = (
    "hit_at_k",
    "recall_at_k",
    "mrr",
    "context_precision",
    "must_contain",
    "groundedness",
    "correctness",
    "latency",
)


def _pack_entry_payload(pack: dict, kind: str) -> dict:
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
async def test_evaluate_pack_uses_enabled_metrics_pack_evaluators(
    client: AsyncClient,
) -> None:
    project = await client.post("/api/v1/projects", json={"name": "Pack Eval"})
    assert project.status_code == 201
    project_id = project.json()["id"]

    ensured = await client.post(f"/api/v1/projects/{project_id}/metrics-pack/ensure")
    assert ensured.status_code == 200, ensured.text
    pack = ensured.json()
    entries = [_pack_entry_payload(pack, kind) for kind in _DEFAULT_PACK_KINDS]
    for entry in entries:
        entry["enabled"] = entry["kind"] == "hit_at_k"
    updated = await client.put(
        f"/api/v1/projects/{project_id}/metrics-pack",
        json={"entries": entries},
    )
    assert updated.status_code == 200, updated.text

    dataset = await client.post(
        f"/api/v1/projects/{project_id}/datasets",
        json={"name": "rag-pack", "task_type": "rag_qa"},
    )
    assert dataset.status_code == 201
    dataset_id = dataset.json()["id"]

    item = await client.post(
        f"/api/v1/datasets/{dataset_id}/items",
        json={
            "input": "q",
            "expected_output": "a",
            "actual_output": "ans",
            "context": {"retrieved_doc_ids": ["target"]},
            "metadata": {"expected_doc_ids": ["target"]},
        },
    )
    assert item.status_code == 201

    experiment = await client.post(
        f"/api/v1/projects/{project_id}/experiments",
        json={"name": "pack-run", "dataset_id": dataset_id},
    )
    assert experiment.status_code == 201
    experiment_id = experiment.json()["id"]

    evaluated = await client.post(f"/api/v1/experiments/{experiment_id}/evaluate-pack")
    assert evaluated.status_code == 200, evaluated.text
    body = evaluated.json()
    assert body["experiment"]["status"] == "completed"
    assert len(body["runs"]) == 1
    assert body["runs"][0]["status"] == "PASSED"
    assert body["runs"][0]["results"][0]["score"] == 1.0


def _metrics_set_entry_from_pack(pack: dict, kind: str) -> dict:
    for entry in pack["entries"]:
        if entry["kind"] == kind:
            return {
                "kind": entry["kind"],
                "enabled": entry["enabled"],
                "threshold": entry["threshold"],
                "config": entry["config"],
                "evaluator_id": entry.get("evaluator_id"),
            }
    raise KeyError(kind)


async def _rag_dataset_with_item(client: AsyncClient, project_id: str, name: str) -> str:
    dataset = await client.post(
        f"/api/v1/projects/{project_id}/datasets",
        json={"name": name, "task_type": "rag_qa"},
    )
    assert dataset.status_code == 201, dataset.text
    dataset_id = dataset.json()["id"]
    item = await client.post(
        f"/api/v1/datasets/{dataset_id}/items",
        json={
            "input": "q",
            "expected_output": "a",
            "actual_output": "ans",
            "context": {"retrieved_doc_ids": ["target"]},
            "metadata": {"expected_doc_ids": ["target"]},
        },
    )
    assert item.status_code == 201, item.text
    return dataset_id


async def _evaluator_kinds_for_runs(
    client: AsyncClient, project_id: str, runs: list[dict]
) -> set[str]:
    listed = await client.get(f"/api/v1/projects/{project_id}/evaluators")
    assert listed.status_code == 200
    by_id = {e["id"]: e for e in listed.json()}
    kinds: set[str] = set()
    for run in runs:
        ev = by_id[str(run["evaluator_id"])]
        kinds.add(str(ev["config"].get("kind", "")))
    return kinds


@pytest.mark.asyncio
async def test_evaluate_pack_body_overrides_experiment_and_project_default(
    client: AsyncClient,
) -> None:
    project = await client.post("/api/v1/projects", json={"name": "Pack Override"})
    assert project.status_code == 201
    project_id = project.json()["id"]

    ensured = await client.post(f"/api/v1/projects/{project_id}/metrics-pack/ensure")
    assert ensured.status_code == 200
    pack = ensured.json()

    custom = await client.post(
        f"/api/v1/projects/{project_id}/metrics-sets",
        json={
            "name": "LatencyOnly",
            "entries": [
                {
                    **_metrics_set_entry_from_pack(pack, "latency"),
                    "enabled": True,
                }
            ],
        },
    )
    assert custom.status_code == 201, custom.text
    custom_id = custom.json()["id"]

    dataset_id = await _rag_dataset_with_item(client, project_id, "override-ds")

    experiment = await client.post(
        f"/api/v1/projects/{project_id}/experiments",
        json={"name": "override-exp", "dataset_id": dataset_id},
    )
    assert experiment.status_code == 201
    experiment_id = experiment.json()["id"]

    evaluated = await client.post(
        f"/api/v1/experiments/{experiment_id}/evaluate-pack",
        json={"metrics_set_id": custom_id},
    )
    assert evaluated.status_code == 200, evaluated.text
    kinds = await _evaluator_kinds_for_runs(client, project_id, evaluated.json()["runs"])
    assert kinds == {"latency"}


@pytest.mark.asyncio
async def test_evaluate_pack_uses_experiment_metrics_set_id(client: AsyncClient) -> None:
    project = await client.post("/api/v1/projects", json={"name": "Pack Pin"})
    project_id = project.json()["id"]

    pack = (await client.post(f"/api/v1/projects/{project_id}/metrics-pack/ensure")).json()
    custom = await client.post(
        f"/api/v1/projects/{project_id}/metrics-sets",
        json={
            "name": "HitOnly",
            "entries": [
                {
                    **_metrics_set_entry_from_pack(pack, "hit_at_k"),
                    "enabled": True,
                }
            ],
        },
    )
    assert custom.status_code == 201
    custom_id = custom.json()["id"]

    dataset_id = await _rag_dataset_with_item(client, project_id, "pin-ds")
    experiment = await client.post(
        f"/api/v1/projects/{project_id}/experiments",
        json={
            "name": "pinned",
            "dataset_id": dataset_id,
            "metrics_set_id": custom_id,
        },
    )
    assert experiment.status_code == 201, experiment.text
    assert experiment.json()["metrics_set_id"] == custom_id
    experiment_id = experiment.json()["id"]

    evaluated = await client.post(
        f"/api/v1/experiments/{experiment_id}/evaluate-pack",
        json={},
    )
    assert evaluated.status_code == 200, evaluated.text
    kinds = await _evaluator_kinds_for_runs(client, project_id, evaluated.json()["runs"])
    assert kinds == {"hit_at_k"}


@pytest.mark.asyncio
async def test_evaluate_pack_save_as_default_persists(client: AsyncClient) -> None:
    project = await client.post("/api/v1/projects", json={"name": "Save Default"})
    project_id = project.json()["id"]
    pack = (await client.post(f"/api/v1/projects/{project_id}/metrics-pack/ensure")).json()
    custom = await client.post(
        f"/api/v1/projects/{project_id}/metrics-sets",
        json={
            "name": "Persist",
            "entries": [_metrics_set_entry_from_pack(pack, "latency")],
        },
    )
    custom_id = custom.json()["id"]

    dataset_id = await _rag_dataset_with_item(client, project_id, "persist-ds")
    experiment = await client.post(
        f"/api/v1/projects/{project_id}/experiments",
        json={"name": "no-pin", "dataset_id": dataset_id},
    )
    experiment_id = experiment.json()["id"]
    assert experiment.json().get("metrics_set_id") is None

    scored = await client.post(
        f"/api/v1/experiments/{experiment_id}/evaluate-pack",
        json={"metrics_set_id": custom_id, "save_as_default": True},
    )
    assert scored.status_code == 200, scored.text

    fetched = await client.get(f"/api/v1/experiments/{experiment_id}")
    assert fetched.status_code == 200
    assert fetched.json()["metrics_set_id"] == custom_id


@pytest.mark.asyncio
async def test_evaluate_pack_foreign_metrics_set_id_is_404(client: AsyncClient) -> None:
    project_a = await client.post("/api/v1/projects", json={"name": "Proj A"})
    project_b = await client.post("/api/v1/projects", json={"name": "Proj B"})
    pid_a = project_a.json()["id"]
    pid_b = project_b.json()["id"]

    pack_b = (await client.post(f"/api/v1/projects/{pid_b}/metrics-pack/ensure")).json()
    custom_b = await client.post(
        f"/api/v1/projects/{pid_b}/metrics-sets",
        json={
            "name": "Bset",
            "entries": [_metrics_set_entry_from_pack(pack_b, "hit_at_k")],
        },
    )
    foreign_id = custom_b.json()["id"]

    dataset_id = await _rag_dataset_with_item(client, pid_a, "foreign-ds")
    experiment = await client.post(
        f"/api/v1/projects/{pid_a}/experiments",
        json={"name": "on-a", "dataset_id": dataset_id},
    )
    experiment_id = experiment.json()["id"]

    resp = await client.post(
        f"/api/v1/experiments/{experiment_id}/evaluate-pack",
        json={"metrics_set_id": foreign_id},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_create_experiment_foreign_metrics_set_id_is_404(client: AsyncClient) -> None:
    project_a = await client.post("/api/v1/projects", json={"name": "Create A"})
    project_b = await client.post("/api/v1/projects", json={"name": "Create B"})
    pid_a = project_a.json()["id"]
    pid_b = project_b.json()["id"]

    pack_b = (await client.post(f"/api/v1/projects/{pid_b}/metrics-pack/ensure")).json()
    custom_b = await client.post(
        f"/api/v1/projects/{pid_b}/metrics-sets",
        json={
            "name": "Other",
            "entries": [_metrics_set_entry_from_pack(pack_b, "hit_at_k")],
        },
    )
    foreign_id = custom_b.json()["id"]

    dataset_id = await _rag_dataset_with_item(client, pid_a, "create-foreign-ds")
    resp = await client.post(
        f"/api/v1/projects/{pid_a}/experiments",
        json={
            "name": "bad-pin",
            "dataset_id": dataset_id,
            "metrics_set_id": foreign_id,
        },
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_ad_hoc_evaluate_ignores_sets(client: AsyncClient) -> None:
    project = await client.post("/api/v1/projects", json={"name": "Ad Hoc"})
    project_id = project.json()["id"]
    pack = (await client.post(f"/api/v1/projects/{project_id}/metrics-pack/ensure")).json()
    custom = await client.post(
        f"/api/v1/projects/{project_id}/metrics-sets",
        json={
            "name": "Ignored",
            "entries": [_metrics_set_entry_from_pack(pack, "latency")],
        },
    )
    custom_id = custom.json()["id"]

    dataset = await client.post(
        f"/api/v1/projects/{project_id}/datasets",
        json={"name": "simple-ds", "task_type": "classification"},
    )
    dataset_id = dataset.json()["id"]
    await client.post(
        f"/api/v1/datasets/{dataset_id}/items",
        json={"input": "q", "expected_output": "a", "actual_output": "a"},
    )

    exact = await client.post(
        f"/api/v1/projects/{project_id}/evaluators",
        json={
            "name": "exact",
            "type": "deterministic",
            "config": {"kind": "exact_match"},
        },
    )
    evaluator_id = exact.json()["id"]

    experiment = await client.post(
        f"/api/v1/projects/{project_id}/experiments",
        json={
            "name": "adhoc",
            "dataset_id": dataset_id,
            "metrics_set_id": custom_id,
        },
    )
    assert experiment.status_code == 201
    experiment_id = experiment.json()["id"]

    evaluated = await client.post(
        f"/api/v1/experiments/{experiment_id}/evaluate",
        json={"evaluator_ids": [evaluator_id]},
    )
    assert evaluated.status_code == 200, evaluated.text
    assert len(evaluated.json()["runs"]) == 1
    assert str(evaluated.json()["runs"][0]["evaluator_id"]) == evaluator_id


@pytest.mark.asyncio
async def test_put_pack_conflict_when_experiment_pins_default_via_create(
    client: AsyncClient,
) -> None:
    project = await client.post("/api/v1/projects", json={"name": "Pack409Eval"})
    project_id = project.json()["id"]
    pack = (await client.post(f"/api/v1/projects/{project_id}/metrics-pack/ensure")).json()
    default_id = pack["id"]

    dataset_id = await _rag_dataset_with_item(client, project_id, "pack409-ds")
    experiment = await client.post(
        f"/api/v1/projects/{project_id}/experiments",
        json={
            "name": "pinned-default",
            "dataset_id": dataset_id,
            "metrics_set_id": default_id,
        },
    )
    assert experiment.status_code == 201, experiment.text

    entries = [_pack_entry_payload(pack, kind) for kind in _DEFAULT_PACK_KINDS]
    conflict = await client.put(
        f"/api/v1/projects/{project_id}/metrics-pack",
        json={"entries": entries},
    )
    assert conflict.status_code == 409
