from __future__ import annotations

import uuid

import pytest

from opengrade_server.application.experiment_metrics import (
    ExperimentParamsLockedError,
    UpdateExperimentParams,
)
from opengrade_server.domain.experiment import Experiment
from support.repositories import InMemoryEvaluationRunRepository, InMemoryExperimentRepository


async def test_params_locked_for_app_config_experiment() -> None:
    experiments = InMemoryExperimentRepository()
    exp = await experiments.add(
        Experiment.create(
            uuid.uuid4(),
            "from-config",
            uuid.uuid4(),
            model_config={"model": "a"},
            app_config_id=uuid.uuid4(),
        )
    )
    use_case = UpdateExperimentParams(experiments, InMemoryEvaluationRunRepository())
    with pytest.raises(ExperimentParamsLockedError, match="app config"):
        await use_case.execute(exp.id, {"model": "b"})


@pytest.mark.parametrize("status", ["running", "completed", "failed"])
async def test_params_locked_when_evaluation_started_without_runs(status: str) -> None:
    experiments = InMemoryExperimentRepository()
    exp = await experiments.add(
        Experiment.create(
            uuid.uuid4(), "evaluating", uuid.uuid4(), model_config={"model": "a"}
        ).with_status(status)
    )
    use_case = UpdateExperimentParams(experiments, InMemoryEvaluationRunRepository())
    with pytest.raises(ExperimentParamsLockedError, match="evaluation"):
        await use_case.execute(exp.id, {"model": "b"})
