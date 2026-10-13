from __future__ import annotations

import uuid

import pytest

from aiobs_server.application.experiment_metrics import (
    ExperimentParamsLockedError,
    UpdateExperimentParams,
)
from aiobs_server.domain.experiment import Experiment
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
