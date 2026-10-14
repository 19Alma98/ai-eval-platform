"""Robustness: experiment crash → failed, 409 while running, startup recovery."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import pytest
from httpx2 import ASGITransport, AsyncClient

from opengrade_server.api.deps import (
    get_app_config_repository,
    get_dataset_repository,
    get_evaluate_background_runner,
    get_evaluation_run_repository,
    get_evaluator_repository,
    get_experiment_item_output_repository,
    get_experiment_repository,
    get_metrics_set_repository,
    get_project_repository,
    get_trace_repository,
)
from opengrade_server.application.evaluate import (
    EvaluateExperiment,
    EvaluateExperimentCommand,
    ExperimentAlreadyRunningError,
)
from opengrade_server.application.scoring_recovery import (
    fail_stuck_experiments,
    requeue_unfinished_live_scores,
)
from opengrade_server.domain.dataset import DatasetItem
from opengrade_server.domain.evaluation import EvaluationRun
from opengrade_server.domain.evaluator import Evaluator
from opengrade_server.domain.experiment import Experiment
from opengrade_server.domain.live_interaction import LiveInteraction
from opengrade_server.main import create_app
from support.repositories import InMemoryAppConfigRepository, InMemoryMetricsSetRepository
from test_api_evaluation import (
    InMemoryDatasetRepository,
    InMemoryEvaluationRunRepository,
    InMemoryEvaluatorRepository,
    InMemoryExperimentItemOutputRepository,
    InMemoryExperimentRepository,
    InMemoryProjectRepository,
    InMemoryTraceRepository,
)


@dataclass
class FakeExperimentRepository:
    experiments: dict[uuid.UUID, Experiment] = field(default_factory=dict)

    async def get_by_id(self, experiment_id: uuid.UUID) -> Experiment | None:
        return self.experiments.get(experiment_id)

    async def list_by_status(self, status: str, *, limit: int = 500) -> list[Experiment]:
        rows = [e for e in self.experiments.values() if e.status == status]
        return rows[:limit]

    async def update(self, experiment: Experiment) -> Experiment:
        self.experiments[experiment.id] = experiment
        return experiment


@dataclass
class FakeDatasetRepository:
    items: dict[uuid.UUID, DatasetItem] = field(default_factory=dict)

    async def list_items(self, dataset_id: uuid.UUID) -> list[DatasetItem]:
        return [i for i in self.items.values() if i.dataset_id == dataset_id]


@dataclass
class FakeEvaluatorRepository:
    evaluators: dict[uuid.UUID, Evaluator] = field(default_factory=dict)

    async def get_by_ids(self, evaluator_ids: list[uuid.UUID]) -> list[Evaluator]:
        return [self.evaluators[i] for i in evaluator_ids if i in self.evaluators]


@dataclass
class FakeEvaluationRunRepository:
    runs: dict[uuid.UUID, EvaluationRun] = field(default_factory=dict)

    async def add_run(self, run: EvaluationRun) -> EvaluationRun:
        self.runs[run.id] = run
        return run

    async def update_run(self, run: EvaluationRun) -> EvaluationRun:
        self.runs[run.id] = run
        return run

    async def list_runs_by_experiment(self, experiment_id: uuid.UUID) -> list[EvaluationRun]:
        return [r for r in self.runs.values() if r.experiment_id == experiment_id]

    async def add_results(self, results: list) -> list:
        return results


@dataclass
class FakeExperimentItemOutputRepository:
    async def list_by_experiment(self, experiment_id: uuid.UUID) -> list:
        return []


class BoomRunner:
    async def run_evaluator(self, **_kwargs: object) -> tuple[EvaluationRun, list]:
        raise RuntimeError("judge exploded")


@pytest.mark.asyncio
async def test_evaluate_exception_marks_experiment_failed() -> None:
    project_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    experiment = Experiment.create(project_id, "exp", dataset_id, model_config={})
    item = DatasetItem.create(dataset_id, input="q", expected_output="a", actual_output="a")
    evaluator = Evaluator.create(project_id, "exact", "deterministic", {"kind": "exact_match"})
    experiments = FakeExperimentRepository(experiments={experiment.id: experiment})
    runs = FakeEvaluationRunRepository()
    use_case = EvaluateExperiment(
        experiments,  # type: ignore[arg-type]
        FakeDatasetRepository(items={item.id: item}),  # type: ignore[arg-type]
        FakeEvaluatorRepository(evaluators={evaluator.id: evaluator}),  # type: ignore[arg-type]
        runs,  # type: ignore[arg-type]
        BoomRunner(),  # type: ignore[arg-type]
        FakeExperimentItemOutputRepository(),  # type: ignore[arg-type]
    )
    with pytest.raises(RuntimeError, match="judge exploded"):
        await use_case.execute(EvaluateExperimentCommand(experiment.id, [evaluator.id]))

    assert experiments.experiments[experiment.id].status == "failed"
    assert len(runs.runs) == 1
    orphan = next(iter(runs.runs.values()))
    assert orphan.status == "ERROR"
    assert "judge exploded" in str(orphan.metadata.get("error", ""))


@pytest.mark.asyncio
async def test_evaluate_rejects_already_running() -> None:
    project_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    experiment = Experiment.create(project_id, "exp", dataset_id, model_config={}, status="running")
    item = DatasetItem.create(dataset_id, input="q", expected_output="a", actual_output="a")
    evaluator = Evaluator.create(project_id, "exact", "deterministic", {"kind": "exact_match"})
    use_case = EvaluateExperiment(
        FakeExperimentRepository(experiments={experiment.id: experiment}),  # type: ignore[arg-type]
        FakeDatasetRepository(items={item.id: item}),  # type: ignore[arg-type]
        FakeEvaluatorRepository(evaluators={evaluator.id: evaluator}),  # type: ignore[arg-type]
        FakeEvaluationRunRepository(),  # type: ignore[arg-type]
        BoomRunner(),  # type: ignore[arg-type]
        FakeExperimentItemOutputRepository(),  # type: ignore[arg-type]
    )
    with pytest.raises(ExperimentAlreadyRunningError):
        await use_case.execute(EvaluateExperimentCommand(experiment.id, [evaluator.id]))


@pytest.mark.asyncio
async def test_fail_stuck_experiments_recovery() -> None:
    project_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    experiment = Experiment.create(
        project_id, "stuck", dataset_id, model_config={}, status="running"
    )
    run = EvaluationRun.create(experiment.id, uuid.uuid4(), status="PENDING")
    experiments = FakeExperimentRepository(experiments={experiment.id: experiment})
    runs = FakeEvaluationRunRepository(runs={run.id: run})
    n = await fail_stuck_experiments(experiments, runs)  # type: ignore[arg-type]
    assert n == 1
    assert experiments.experiments[experiment.id].status == "failed"
    assert runs.runs[run.id].status == "ERROR"


@dataclass
class FakeLiveRepository:
    items: dict[uuid.UUID, LiveInteraction] = field(default_factory=dict)
    scheduled: list[uuid.UUID] = field(default_factory=list)

    async def update(self, interaction: LiveInteraction) -> LiveInteraction:
        self.items[interaction.id] = interaction
        return interaction

    async def list_by_judge_statuses(
        self,
        statuses: frozenset[str] | set[str],
        *,
        limit: int = 500,
    ) -> list[LiveInteraction]:
        return [i for i in self.items.values() if i.judge_status in statuses][:limit]


@pytest.mark.asyncio
async def test_requeue_unfinished_live_resets_running(monkeypatch: pytest.MonkeyPatch) -> None:
    scheduled: list[uuid.UUID] = []

    async def fake_schedule(interaction_id: uuid.UUID) -> None:
        scheduled.append(interaction_id)

    monkeypatch.setattr(
        "opengrade_server.application.scoring_recovery.schedule_live_score",
        fake_schedule,
    )

    pending = LiveInteraction.create(uuid.uuid4(), "q1", "a1")
    running = LiveInteraction.create(uuid.uuid4(), "q2", "a2")
    running = running.with_status("running")
    live = FakeLiveRepository(items={pending.id: pending, running.id: running})

    n = await requeue_unfinished_live_scores(live)  # type: ignore[arg-type]
    assert n == 2
    assert live.items[running.id].judge_status == "pending"
    # create_task schedules the pump; give the event loop a turn
    import asyncio

    await asyncio.sleep(0.05)
    assert set(scheduled) == {pending.id, running.id}


@pytest.fixture
async def robustness_client() -> AsyncIterator[tuple[AsyncClient, InMemoryExperimentRepository]]:
    import os

    from opengrade_server.config import get_settings

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

    async def noop_background(_command: object) -> None:
        return None

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
    app.dependency_overrides[get_evaluate_background_runner] = lambda: noop_background

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, experiments

    app.dependency_overrides.clear()
    os.environ.pop("CONTENT_CAPTURE_ENABLED", None)
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_evaluate_pack_409_when_already_running(
    robustness_client: tuple[AsyncClient, InMemoryExperimentRepository],
) -> None:
    client, _experiments = robustness_client
    project = await client.post("/api/v1/projects", json={"name": "Conflict"})
    project_id = project.json()["id"]
    await client.post(f"/api/v1/projects/{project_id}/metrics-pack/ensure")
    dataset = await client.post(
        f"/api/v1/projects/{project_id}/datasets",
        json={"name": "ds", "task_type": "rag_qa"},
    )
    dataset_id = dataset.json()["id"]
    await client.post(
        f"/api/v1/datasets/{dataset_id}/items",
        json={
            "input": "q",
            "expected_output": "a",
            "actual_output": "a",
            "context": {"retrieved_doc_ids": ["d"]},
            "metadata": {"expected_doc_ids": ["d"]},
        },
    )
    experiment = await client.post(
        f"/api/v1/projects/{project_id}/experiments",
        json={"name": "e", "dataset_id": dataset_id},
    )
    experiment_id = experiment.json()["id"]

    first = await client.post(f"/api/v1/experiments/{experiment_id}/evaluate-pack")
    assert first.status_code == 202, first.text
    assert first.json()["status"] == "running"

    second = await client.post(f"/api/v1/experiments/{experiment_id}/evaluate-pack")
    assert second.status_code == 409, second.text
