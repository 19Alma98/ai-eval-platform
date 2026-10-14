"""Experiment params and experiment-level scalar metrics (MLflow-style logging)."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from aiobs_server.application.experiments import ExperimentNotFoundError
from aiobs_server.domain.experiment import Experiment
from aiobs_server.domain.experiment_metric import validate_experiment_metrics
from aiobs_server.domain.repositories import (
    EvaluationRunRepository,
    ExperimentMetricRepository,
    ExperimentRepository,
)


class ExperimentParamsLockedError(Exception):
    pass


class LogExperimentMetrics:
    def __init__(
        self, experiments: ExperimentRepository, metrics: ExperimentMetricRepository
    ) -> None:
        self._experiments = experiments
        self._metrics = metrics

    async def execute(
        self, experiment_id: uuid.UUID, metrics: Mapping[str, Any]
    ) -> dict[str, float]:
        if await self._experiments.get_by_id(experiment_id) is None:
            raise ExperimentNotFoundError(experiment_id)
        return await self._metrics.upsert(experiment_id, validate_experiment_metrics(metrics))


class GetExperimentMetrics:
    def __init__(
        self, experiments: ExperimentRepository, metrics: ExperimentMetricRepository
    ) -> None:
        self._experiments = experiments
        self._metrics = metrics

    async def execute(self, experiment_id: uuid.UUID) -> dict[str, float]:
        if await self._experiments.get_by_id(experiment_id) is None:
            raise ExperimentNotFoundError(experiment_id)
        return await self._metrics.get(experiment_id)


class UpdateExperimentParams:
    """Merge params into ``model_config`` while nothing has been scored yet.

    Scored results must keep describing the config they were produced with, and an
    app-config experiment's params are the config snapshot itself.
    """

    def __init__(self, experiments: ExperimentRepository, runs: EvaluationRunRepository) -> None:
        self._experiments = experiments
        self._runs = runs

    async def execute(self, experiment_id: uuid.UUID, params: Mapping[str, Any]) -> Experiment:
        experiment = await self._experiments.get_by_id(experiment_id)
        if experiment is None:
            raise ExperimentNotFoundError(experiment_id)
        if not params:
            raise ValueError("params must not be empty")
        if experiment.app_config_id is not None:
            raise ExperimentParamsLockedError(
                "params are locked: they come from the app config snapshot; "
                "create a new experiment instead"
            )
        # Evaluate flows set status away from "created" before any run row exists;
        # client-results / outputs never touch status, so runs are checked too.
        if experiment.status != "created" or await self._runs.list_runs_by_experiment(
            experiment_id
        ):
            raise ExperimentParamsLockedError(
                "params are locked: the experiment already has evaluation runs; "
                "create a new experiment instead"
            )
        merged = {**experiment.model_config, **dict(params)}
        return await self._experiments.update(experiment.with_model_config(merged))
