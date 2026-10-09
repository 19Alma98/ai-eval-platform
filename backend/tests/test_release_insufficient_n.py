from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock

import pytest

from aiobs_server.application.compare import ExperimentComparison
from aiobs_server.application.release_check import ReleaseCheck, ReleaseCheckCommand
from aiobs_server.domain.evaluation import EvaluationRun
from aiobs_server.domain.experiment import Experiment
from aiobs_server.domain.project import Project
from aiobs_server.regression.aggregate import MetricComparison


class _Projects:
    def __init__(self, project: Project) -> None:
        self._project = project

    async def get_by_id(self, project_id: uuid.UUID) -> Project | None:
        return self._project if self._project.id == project_id else None


class _Experiments:
    def __init__(self, *experiments: Experiment) -> None:
        self._by_id = {e.id: e for e in experiments}

    async def get_by_id(self, experiment_id: uuid.UUID) -> Experiment | None:
        return self._by_id.get(experiment_id)


class _Runs:
    async def list_runs_by_experiment(self, experiment_id: uuid.UUID) -> list[EvaluationRun]:
        return []

    async def list_results(self, run_id: uuid.UUID) -> list[Any]:
        return []


def _metric(*, status: str, delta: float | None) -> MetricComparison:
    return MetricComparison(
        evaluator_id=uuid.uuid4(),
        evaluator_name="quality",
        metric="mean_score",
        candidate=0.5,
        baseline=0.9,
        delta=delta,
        status=status,  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_release_check_regression_only_soft_passes_insufficient_n() -> None:
    project = Project.create("p")
    dataset_id = uuid.uuid4()
    baseline = Experiment.create(project.id, "baseline", dataset_id)
    candidate = Experiment.create(
        project.id,
        "candidate",
        dataset_id,
        baseline_experiment_id=baseline.id,
    )
    metric = _metric(status="insufficient_n", delta=-0.4)
    comparison = ExperimentComparison(
        experiment_id=candidate.id,
        baseline_experiment_id=baseline.id,
        metrics=[metric],
        regressions=[],
        improved=[],
        unchanged=[],
        config_mismatches=[],
        insufficient_n=[metric],
    )
    compare = AsyncMock()
    compare.execute = AsyncMock(return_value=comparison)

    result = await ReleaseCheck(
        _Projects(project),
        _Experiments(candidate, baseline),
        _Runs(),
        compare,
    ).execute(
        ReleaseCheckCommand(
            project_id=project.id,
            experiment_id=candidate.id,
            policy={"regression": {"max_delta": -0.03}},
            baseline_experiment_id=baseline.id,
        )
    )
    assert result.status == "passed"
    assert not any(c.status == "failed" for c in result.checks.checks)
    assert not any(c.status == "unavailable" for c in result.checks.checks)


@pytest.mark.asyncio
async def test_release_check_still_fails_real_regression() -> None:
    project = Project.create("p")
    dataset_id = uuid.uuid4()
    baseline = Experiment.create(project.id, "baseline", dataset_id)
    candidate = Experiment.create(
        project.id,
        "candidate",
        dataset_id,
        baseline_experiment_id=baseline.id,
    )
    metric = _metric(status="regression", delta=-0.4)
    comparison = ExperimentComparison(
        experiment_id=candidate.id,
        baseline_experiment_id=baseline.id,
        metrics=[metric],
        regressions=[metric],
        improved=[],
        unchanged=[],
        config_mismatches=[],
        insufficient_n=[],
    )
    compare = AsyncMock()
    compare.execute = AsyncMock(return_value=comparison)

    result = await ReleaseCheck(
        _Projects(project),
        _Experiments(candidate, baseline),
        _Runs(),
        compare,
    ).execute(
        ReleaseCheckCommand(
            project_id=project.id,
            experiment_id=candidate.id,
            policy={"regression": {"max_delta": -0.03}},
            baseline_experiment_id=baseline.id,
        )
    )
    assert result.status == "failed"
    assert any(
        c.metric == "regression.quality.mean_score" and c.status == "failed"
        for c in result.checks.checks
    )
