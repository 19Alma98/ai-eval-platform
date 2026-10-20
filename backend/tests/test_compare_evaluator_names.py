from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from opengrade_server.application.compare import (
    CompareExperiments,
    InvalidCompareSelectionError,
    SummarizeExperiment,
)
from opengrade_server.application.compare_items import CompareExperimentItems
from opengrade_server.domain.evaluation import EvaluationResultRecord, EvaluationRun
from opengrade_server.domain.evaluator import Evaluator
from opengrade_server.domain.experiment import Experiment


class _FakeExperiments:
    def __init__(self, *experiments: Experiment) -> None:
        self._by_id = {e.id: e for e in experiments}

    async def get_by_id(self, experiment_id: uuid.UUID) -> Experiment | None:
        return self._by_id.get(experiment_id)


class _FakeRuns:
    def __init__(
        self,
        runs: list[EvaluationRun],
        results: dict[uuid.UUID, list[EvaluationResultRecord]],
    ) -> None:
        self._runs = runs
        self._results = results

    async def list_runs_by_experiment(self, experiment_id: uuid.UUID) -> list[EvaluationRun]:
        return [r for r in self._runs if r.experiment_id == experiment_id]

    async def list_run_ids_with_results(self, experiment_id: uuid.UUID) -> set[uuid.UUID]:
        run_ids = {r.id for r in self._runs if r.experiment_id == experiment_id}
        return {run_id for run_id, rows in self._results.items() if run_id in run_ids and rows}

    async def list_results(self, run_id: uuid.UUID) -> list[EvaluationResultRecord]:
        return list(self._results.get(run_id, []))


class _FakeEvaluators:
    def __init__(self, *evaluators: Evaluator) -> None:
        self._by_id = {e.id: e for e in evaluators}

    async def get_by_ids(self, evaluator_ids: list[uuid.UUID]) -> list[Evaluator]:
        return [self._by_id[i] for i in evaluator_ids if i in self._by_id]


def _experiment(dataset_id: uuid.UUID) -> Experiment:
    return Experiment.create(
        project_id=uuid.uuid4(),
        name="exp",
        dataset_id=dataset_id,
    )


def _evaluator(name: str = "exact") -> Evaluator:
    return Evaluator.create(
        project_id=uuid.uuid4(),
        name=name,
        type="deterministic",
        config={"kind": "exact_match"},
    )


def _run(
    experiment_id: uuid.UUID,
    evaluator_id: uuid.UUID,
    *,
    metadata: dict | None = None,
) -> EvaluationRun:
    return EvaluationRun(
        id=uuid.uuid4(),
        experiment_id=experiment_id,
        evaluator_id=evaluator_id,
        status="PASSED",
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        metadata=dict(metadata or {}),
    )


@pytest.mark.asyncio
async def test_summary_resolves_evaluator_name_from_registry() -> None:
    dataset_id = uuid.uuid4()
    experiment = _experiment(dataset_id)
    evaluator = _evaluator("from-registry")
    run = _run(experiment.id, evaluator.id, metadata={})
    result = EvaluationResultRecord.create(run.id, uuid.uuid4(), score=1.0, label="pass")

    summary = await SummarizeExperiment(
        _FakeExperiments(experiment),
        _FakeRuns([run], {run.id: [result]}),
        _FakeEvaluators(evaluator),
    ).execute(experiment.id)

    assert len(summary.evaluators) == 1
    assert summary.evaluators[0].evaluator_name == "from-registry"


@pytest.mark.asyncio
async def test_summary_prefers_metadata_evaluator_name() -> None:
    dataset_id = uuid.uuid4()
    experiment = _experiment(dataset_id)
    evaluator = _evaluator("from-registry")
    run = _run(
        experiment.id,
        evaluator.id,
        metadata={"evaluator_name": "from-metadata"},
    )
    result = EvaluationResultRecord.create(run.id, uuid.uuid4(), score=1.0, label="pass")

    summary = await SummarizeExperiment(
        _FakeExperiments(experiment),
        _FakeRuns([run], {run.id: [result]}),
        _FakeEvaluators(evaluator),
    ).execute(experiment.id)

    assert summary.evaluators[0].evaluator_name == "from-metadata"


@pytest.mark.asyncio
async def test_compare_resolves_evaluator_name_from_registry() -> None:
    dataset_id = uuid.uuid4()
    baseline = _experiment(dataset_id)
    candidate = Experiment.create(
        project_id=baseline.project_id,
        name="candidate",
        dataset_id=dataset_id,
        baseline_experiment_id=baseline.id,
    )
    evaluator = _evaluator("exact")
    base_run = _run(baseline.id, evaluator.id, metadata={})
    cand_run = _run(candidate.id, evaluator.id, metadata={})
    base_result = EvaluationResultRecord.create(base_run.id, uuid.uuid4(), score=1.0, label="pass")
    cand_result = EvaluationResultRecord.create(cand_run.id, uuid.uuid4(), score=0.5, label="fail")

    comparison = await CompareExperiments(
        _FakeExperiments(baseline, candidate),
        _FakeRuns(
            [base_run, cand_run],
            {base_run.id: [base_result], cand_run.id: [cand_result]},
        ),
        _FakeEvaluators(evaluator),
    ).execute(candidate.id, baseline.id)

    assert comparison.metrics
    assert all(m.evaluator_name == "exact" for m in comparison.metrics)


class _FakeDatasets:
    async def count_items(self, dataset_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
        return {d: len(await self.list_items(d)) for d in dataset_ids}

    async def list_items(self, dataset_id: uuid.UUID) -> list:
        return []


class _FakeOutputs:
    async def list_by_experiment(self, experiment_id: uuid.UUID) -> list:
        return []


class _FixedFingerprint:
    def __init__(self, value: str) -> None:
        self._value = value

    async def execute(self, experiment: Experiment) -> str:
        return self._value


@pytest.mark.asyncio
async def test_compare_items_rejects_stale_baseline_runs() -> None:
    dataset_id = uuid.uuid4()
    baseline = _experiment(dataset_id)
    candidate = Experiment.create(
        project_id=baseline.project_id,
        name="candidate",
        dataset_id=dataset_id,
        baseline_experiment_id=baseline.id,
    )
    evaluator = _evaluator("exact")
    base_run = _run(baseline.id, evaluator.id, metadata={"inputs_fingerprint": "old"})
    cand_run = _run(candidate.id, evaluator.id, metadata={"inputs_fingerprint": "new"})

    use_case = CompareExperimentItems(
        _FakeExperiments(baseline, candidate),
        _FakeDatasets(),
        _FakeRuns([base_run, cand_run], {}),
        _FakeOutputs(),
        _FixedFingerprint("new"),
    )
    with pytest.raises(InvalidCompareSelectionError, match="re-score"):
        await use_case.execute(candidate.id, baseline.id)
