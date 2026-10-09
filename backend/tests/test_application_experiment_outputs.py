from __future__ import annotations

import uuid
from dataclasses import dataclass, field

import pytest

from aiobs_server.application.evaluate import EvaluateExperiment, EvaluateExperimentCommand
from aiobs_server.application.experiment_outputs import (
    ExperimentItemNotInDatasetError,
    ListExperimentOutputs,
    UpsertExperimentOutputs,
    UpsertOutputItem,
    merge_dataset_item,
    resolve_item_fields,
)
from aiobs_server.application.experiments import ExperimentNotFoundError
from aiobs_server.domain.dataset import DatasetItem
from aiobs_server.domain.evaluator import Evaluator
from aiobs_server.domain.experiment import Experiment
from aiobs_server.domain.experiment_output import ExperimentItemOutput
from aiobs_server.evaluation.deterministic import register_deterministic_evaluators
from aiobs_server.evaluation.registry import clear_registry
from aiobs_server.evaluation.runner import EvaluationRunner


def test_resolve_prefers_experiment_then_legacy() -> None:
    item = DatasetItem.create(uuid.uuid4(), input="q", actual_output="legacy", context={"c": 1})
    out = ExperimentItemOutput.create(uuid.uuid4(), item.id, actual_output="new", context=None)
    actual, ctx = resolve_item_fields(item, out)
    assert actual == "new"
    assert ctx == {"c": 1}


def test_resolve_no_output_row_uses_legacy() -> None:
    item = DatasetItem.create(uuid.uuid4(), input="q", actual_output="legacy")
    assert resolve_item_fields(item, None) == ("legacy", None)


def test_resolve_without_fallback_ignores_dataset_fields() -> None:
    item = DatasetItem.create(uuid.uuid4(), input="q", actual_output="legacy", context={"c": 1})
    out = ExperimentItemOutput.create(uuid.uuid4(), item.id, actual_output="new", context=None)
    assert resolve_item_fields(item, out, fallback_to_item=False) == ("new", None)
    assert resolve_item_fields(item, None, fallback_to_item=False) == (None, None)


def test_merge_includes_output_metadata_but_item_gold_wins() -> None:
    item = DatasetItem.create(uuid.uuid4(), input="q", metadata={"expected_doc_ids": ["gold"]})
    out = ExperimentItemOutput.create(
        uuid.uuid4(),
        item.id,
        actual_output="a",
        metadata={"source_trace_id": "t1", "expected_doc_ids": ["spoofed"]},
    )
    merged = merge_dataset_item(item, out)
    assert merged.metadata == {"source_trace_id": "t1", "expected_doc_ids": ["gold"]}


def test_merge_dataset_item_keeps_id_and_resolves_fields() -> None:
    dataset_id = uuid.uuid4()
    item = DatasetItem.create(dataset_id, input="q", actual_output="legacy", context={"k": 1})
    out = ExperimentItemOutput.create(uuid.uuid4(), item.id, actual_output="exp", context=None)
    merged = merge_dataset_item(item, out)
    assert merged.id == item.id
    assert merged.dataset_id == dataset_id
    assert merged.input == "q"
    assert merged.actual_output == "exp"
    assert merged.context == {"k": 1}


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

    async def get_item(self, item_id: uuid.UUID) -> DatasetItem | None:
        return self.items.get(item_id)

    async def list_items(self, dataset_id: uuid.UUID) -> list[DatasetItem]:
        return [i for i in self.items.values() if i.dataset_id == dataset_id]


@dataclass
class FakeExperimentItemOutputRepository:
    outputs: dict[tuple[uuid.UUID, uuid.UUID], ExperimentItemOutput] = field(default_factory=dict)

    async def get(
        self, experiment_id: uuid.UUID, dataset_item_id: uuid.UUID
    ) -> ExperimentItemOutput | None:
        return self.outputs.get((experiment_id, dataset_item_id))

    async def upsert_many(self, outputs: list[ExperimentItemOutput]) -> list[ExperimentItemOutput]:
        for output in outputs:
            self.outputs[(output.experiment_id, output.dataset_item_id)] = output
        return outputs

    async def list_by_experiment(self, experiment_id: uuid.UUID) -> list[ExperimentItemOutput]:
        return sorted(
            (o for (eid, _), o in self.outputs.items() if eid == experiment_id),
            key=lambda o: o.dataset_item_id,
        )


@pytest.mark.asyncio
async def test_upsert_rejects_item_from_another_dataset() -> None:
    experiment_dataset = uuid.uuid4()
    other_dataset = uuid.uuid4()
    experiment = Experiment.create(uuid.uuid4(), "exp", experiment_dataset, model_config={})
    foreign_item = DatasetItem.create(other_dataset, input="x")
    experiments = FakeExperimentRepository({experiment.id: experiment})
    datasets = FakeDatasetRepository({foreign_item.id: foreign_item})
    outputs = FakeExperimentItemOutputRepository()
    use_case = UpsertExperimentOutputs(experiments, datasets, outputs)

    with pytest.raises(ExperimentItemNotInDatasetError):
        await use_case.execute(
            experiment.id,
            [UpsertOutputItem(dataset_item_id=foreign_item.id, actual_output="y")],
        )


@pytest.mark.asyncio
async def test_upsert_missing_experiment_raises() -> None:
    missing_id = uuid.uuid4()
    use_case = UpsertExperimentOutputs(
        FakeExperimentRepository(),
        FakeDatasetRepository(),
        FakeExperimentItemOutputRepository(),
    )
    with pytest.raises(ExperimentNotFoundError):
        await use_case.execute(
            missing_id,
            [UpsertOutputItem(dataset_item_id=uuid.uuid4(), actual_output="x")],
        )


@pytest.mark.asyncio
async def test_upsert_creates_and_patches_outputs() -> None:
    dataset_id = uuid.uuid4()
    experiment = Experiment.create(uuid.uuid4(), "exp", dataset_id, model_config={})
    item = DatasetItem.create(dataset_id, input="q")
    experiments = FakeExperimentRepository({experiment.id: experiment})
    datasets = FakeDatasetRepository({item.id: item})
    output_repo = FakeExperimentItemOutputRepository()
    use_case = UpsertExperimentOutputs(experiments, datasets, output_repo)

    created = await use_case.execute(
        experiment.id,
        [
            UpsertOutputItem(
                dataset_item_id=item.id,
                actual_output="a1",
                context={"c": 1},
                metadata={"m": 1},
            )
        ],
    )
    assert len(created) == 1
    assert created[0].actual_output == "a1"
    assert created[0].context == {"c": 1}
    assert created[0].metadata == {"m": 1}

    updated = await use_case.execute(
        experiment.id,
        [UpsertOutputItem(dataset_item_id=item.id, actual_output="a2")],
    )
    assert len(updated) == 1
    assert updated[0].id == created[0].id
    assert updated[0].actual_output == "a2"
    assert updated[0].context == {"c": 1}
    assert updated[0].metadata == {"m": 1}


@pytest.mark.asyncio
async def test_upsert_unset_preserves_existing_fields() -> None:
    dataset_id = uuid.uuid4()
    experiment = Experiment.create(uuid.uuid4(), "exp", dataset_id, model_config={})
    item = DatasetItem.create(dataset_id, input="q")
    experiments = FakeExperimentRepository({experiment.id: experiment})
    datasets = FakeDatasetRepository({item.id: item})
    output_repo = FakeExperimentItemOutputRepository()
    use_case = UpsertExperimentOutputs(experiments, datasets, output_repo)
    await use_case.execute(
        experiment.id,
        [UpsertOutputItem(dataset_item_id=item.id, actual_output="keep", context={"x": 1})],
    )
    patched = await use_case.execute(
        experiment.id,
        [UpsertOutputItem(dataset_item_id=item.id, context=None)],
    )
    assert patched[0].actual_output == "keep"
    assert patched[0].context is None


@pytest.mark.asyncio
async def test_list_outputs_requires_experiment() -> None:
    missing_id = uuid.uuid4()
    use_case = ListExperimentOutputs(
        FakeExperimentRepository(),
        FakeExperimentItemOutputRepository(),
    )
    with pytest.raises(ExperimentNotFoundError):
        await use_case.execute(missing_id)


@pytest.mark.asyncio
async def test_list_outputs_returns_repository_rows() -> None:
    dataset_id = uuid.uuid4()
    experiment = Experiment.create(uuid.uuid4(), "exp", dataset_id, model_config={})
    item = DatasetItem.create(dataset_id, input="q")
    out = ExperimentItemOutput.create(experiment.id, item.id, actual_output="v", context=None)
    output_repo = FakeExperimentItemOutputRepository({(experiment.id, item.id): out})
    use_case = ListExperimentOutputs(
        FakeExperimentRepository({experiment.id: experiment}),
        output_repo,
    )
    listed = await use_case.execute(experiment.id)
    assert listed == [out]


@dataclass
class FakeEvaluatorRepository:
    evaluators: dict[uuid.UUID, Evaluator] = field(default_factory=dict)

    async def get_by_ids(self, evaluator_ids: list[uuid.UUID]) -> list[Evaluator]:
        return [self.evaluators[i] for i in evaluator_ids if i in self.evaluators]


@dataclass
class FakeEvaluationRunRepository:
    runs: dict[uuid.UUID, object] = field(default_factory=dict)
    results: list[object] = field(default_factory=list)

    async def add_run(self, run):
        self.runs[run.id] = run
        return run

    async def update_run(self, run):
        self.runs[run.id] = run
        return run

    async def add_results(self, results):
        self.results.extend(results)
        return results


@pytest.fixture(autouse=True)
def _evaluator_registry() -> None:
    clear_registry()
    register_deterministic_evaluators()
    yield
    clear_registry()


@pytest.mark.asyncio
async def test_evaluate_prefers_experiment_output_over_legacy() -> None:
    project_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    experiment = Experiment.create(project_id, "exp", dataset_id, model_config={})
    item = DatasetItem.create(
        dataset_id,
        input="q",
        expected_output="candidate",
        actual_output="legacy",
    )
    evaluator = Evaluator.create(
        project_id,
        "exact",
        "deterministic",
        {"kind": "exact_match"},
    )
    out = ExperimentItemOutput.create(
        experiment.id, item.id, actual_output="candidate", context=None
    )
    output_repo = FakeExperimentItemOutputRepository({(experiment.id, item.id): out})
    use_case = EvaluateExperiment(
        FakeExperimentRepository({experiment.id: experiment}),
        FakeDatasetRepository({item.id: item}),
        FakeEvaluatorRepository({evaluator.id: evaluator}),
        FakeEvaluationRunRepository(),
        EvaluationRunner(max_concurrency=1),
        output_repo,
    )
    result = await use_case.execute(EvaluateExperimentCommand(experiment.id, [evaluator.id]))
    scores = [r.score for r in result.results_by_run[next(iter(result.results_by_run))]]
    assert scores == [1.0]


@pytest.mark.asyncio
async def test_evaluate_without_experiment_output_uses_legacy() -> None:
    project_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    experiment = Experiment.create(project_id, "exp", dataset_id, model_config={})
    item = DatasetItem.create(
        dataset_id,
        input="q",
        expected_output="legacy",
        actual_output="legacy",
    )
    evaluator = Evaluator.create(
        project_id,
        "exact",
        "deterministic",
        {"kind": "exact_match"},
    )
    use_case = EvaluateExperiment(
        FakeExperimentRepository({experiment.id: experiment}),
        FakeDatasetRepository({item.id: item}),
        FakeEvaluatorRepository({evaluator.id: evaluator}),
        FakeEvaluationRunRepository(),
        EvaluationRunner(max_concurrency=1),
        FakeExperimentItemOutputRepository(),
    )
    result = await use_case.execute(EvaluateExperimentCommand(experiment.id, [evaluator.id]))
    scores = [r.score for r in result.results_by_run[next(iter(result.results_by_run))]]
    assert scores == [1.0]


@pytest.mark.asyncio
async def test_evaluate_partial_outputs_fails_missing_items_without_legacy_fallback() -> None:
    project_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    experiment = Experiment.create(project_id, "exp", dataset_id, model_config={})
    answered = DatasetItem.create(dataset_id, input="q1", expected_output="a")
    # Dataset carries a stale inline answer that matches gold: must NOT be used.
    unanswered = DatasetItem.create(dataset_id, input="q2", expected_output="b", actual_output="b")
    evaluator = Evaluator.create(project_id, "exact", "deterministic", {"kind": "exact_match"})
    out = ExperimentItemOutput.create(experiment.id, answered.id, actual_output="a", context=None)
    use_case = EvaluateExperiment(
        FakeExperimentRepository({experiment.id: experiment}),
        FakeDatasetRepository({answered.id: answered, unanswered.id: unanswered}),
        FakeEvaluatorRepository({evaluator.id: evaluator}),
        FakeEvaluationRunRepository(),
        EvaluationRunner(max_concurrency=1),
        FakeExperimentItemOutputRepository({(experiment.id, answered.id): out}),
    )
    result = await use_case.execute(EvaluateExperimentCommand(experiment.id, [evaluator.id]))
    by_item = {
        r.dataset_item_id: r for r in result.results_by_run[next(iter(result.results_by_run))]
    }
    assert by_item[answered.id].label == "PASS"
    assert by_item[unanswered.id].label == "FAIL"
    assert by_item[unanswered.id].score == 0.0


@pytest.mark.asyncio
async def test_evaluate_applies_config_overrides() -> None:
    project_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    experiment = Experiment.create(project_id, "exp", dataset_id, model_config={})
    item = DatasetItem.create(dataset_id, input="q", expected_output="HELLO", actual_output="hello")
    evaluator = Evaluator.create(
        project_id, "exact", "deterministic", {"kind": "exact_match", "case_sensitive": True}
    )
    use_case = EvaluateExperiment(
        FakeExperimentRepository({experiment.id: experiment}),
        FakeDatasetRepository({item.id: item}),
        FakeEvaluatorRepository({evaluator.id: evaluator}),
        FakeEvaluationRunRepository(),
        EvaluationRunner(max_concurrency=1),
        FakeExperimentItemOutputRepository(),
    )
    result = await use_case.execute(
        EvaluateExperimentCommand(
            experiment.id,
            [evaluator.id],
            config_overrides={evaluator.id: {"case_sensitive": False}},
        )
    )
    scores = [r.score for r in result.results_by_run[next(iter(result.results_by_run))]]
    assert scores == [1.0]
