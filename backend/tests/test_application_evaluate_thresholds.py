from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

import pytest

from aiobs.application.evaluate import (
    EvaluateExperiment,
    EvaluateExperimentCommand,
    EvaluateExperimentResult,
    ScoreExperimentFromPack,
    ScoreExperimentFromPackCommand,
)
from aiobs.domain.dataset import DatasetItem
from aiobs.domain.evaluation import EvaluationRun
from aiobs.domain.evaluator import Evaluator
from aiobs.domain.experiment import Experiment
from aiobs.domain.metrics_set import MetricsSet, MetricsSetEntry


@dataclass
class FakeExperimentRepository:
    experiments: dict[uuid.UUID, Experiment] = field(default_factory=dict)

    async def get_by_id(self, experiment_id: uuid.UUID) -> Experiment | None:
        return self.experiments.get(experiment_id)

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

    async def add_results(self, results: list) -> list:
        return results


@dataclass
class FakeExperimentItemOutputRepository:
    async def list_by_experiment(self, experiment_id: uuid.UUID) -> list:
        return []


class SpyRunner:
    def __init__(self) -> None:
        self.thresholds: list[float | None] = []

    async def run_evaluator(
        self,
        *,
        run: EvaluationRun,
        evaluator_entity: Evaluator,
        items: list[DatasetItem],
        pass_threshold: float | None = None,
        **_kwargs: object,
    ) -> tuple[EvaluationRun, list]:
        self.thresholds.append(pass_threshold)
        finished = run.with_status("PASSED", finished_at=datetime.now(UTC))
        return finished, []


@pytest.mark.asyncio
async def test_evaluate_forwards_pass_threshold_to_runner() -> None:
    project_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    experiment = Experiment.create(project_id, "exp", dataset_id, model_config={})
    item = DatasetItem.create(dataset_id, input="q", expected_output="a", actual_output="a")
    evaluator = Evaluator.create(project_id, "exact", "deterministic", {"kind": "exact_match"})
    spy = SpyRunner()
    use_case = EvaluateExperiment(
        FakeExperimentRepository({experiment.id: experiment}),
        FakeDatasetRepository({item.id: item}),
        FakeEvaluatorRepository({evaluator.id: evaluator}),
        FakeEvaluationRunRepository(),
        spy,  # type: ignore[arg-type]
        FakeExperimentItemOutputRepository(),
    )
    await use_case.execute(
        EvaluateExperimentCommand(
            experiment.id,
            [evaluator.id],
            pass_thresholds={evaluator.id: 0.8},
        )
    )
    assert spy.thresholds == [0.8]


@pytest.mark.asyncio
async def test_score_from_pack_builds_pass_thresholds_map() -> None:
    project_id = uuid.uuid4()
    experiment = Experiment.create(project_id, "exp", uuid.uuid4(), model_config={})
    e1 = uuid.uuid4()
    e2 = uuid.uuid4()
    metrics_set = MetricsSet.create(
        project_id,
        "pack",
        entries=(
            MetricsSetEntry(
                id=uuid.uuid4(),
                kind="correctness",
                enabled=True,
                threshold=0.7,
                config={},
                evaluator_id=e1,
                is_default=False,
            ),
            MetricsSetEntry(
                id=uuid.uuid4(),
                kind="latency",
                enabled=True,
                threshold=None,
                config={"max_ms": 1200},
                evaluator_id=e2,
                is_default=False,
            ),
            MetricsSetEntry(
                id=uuid.uuid4(),
                kind="groundedness",
                enabled=False,
                threshold=0.9,
                config={},
                evaluator_id=uuid.uuid4(),
                is_default=False,
            ),
        ),
    )

    class FakeResolve:
        async def execute(self, **kwargs):
            return replace(
                metrics_set,
                entries=tuple(replace(e, evaluator_id=e.evaluator_id) for e in metrics_set.entries),
            )

    class CapturingEvaluate:
        def __init__(self) -> None:
            self.command: EvaluateExperimentCommand | None = None

        async def execute(self, command: EvaluateExperimentCommand) -> EvaluateExperimentResult:
            self.command = command
            return EvaluateExperimentResult(experiment=experiment, runs=[], results_by_run={})

    capture = CapturingEvaluate()
    use_case = ScoreExperimentFromPack(
        FakeExperimentRepository({experiment.id: experiment}),
        FakeResolve(),  # type: ignore[arg-type]
        capture,  # type: ignore[arg-type]
    )
    await use_case.execute(ScoreExperimentFromPackCommand(experiment_id=experiment.id))
    assert capture.command is not None
    assert capture.command.evaluator_ids == [e1, e2]
    assert capture.command.pass_thresholds == {e1: 0.7, e2: None}
    assert capture.command.config_overrides == {e1: {}, e2: {"max_ms": 1200}}
