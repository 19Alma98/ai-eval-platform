from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from aiobs_server.application.app_configs import AppConfigNotFoundError
from aiobs_server.application.datasets import DatasetNotFoundError
from aiobs_server.application.metrics_sets import MetricsSetNotFoundError
from aiobs_server.application.projects import ProjectNotFoundError
from aiobs_server.domain.app_config import AppConfig
from aiobs_server.domain.experiment import Experiment
from aiobs_server.domain.repositories import (
    AppConfigRepository,
    DatasetRepository,
    ExperimentRepository,
    MetricsSetRepository,
    ProjectRepository,
)


class ExperimentNotFoundError(Exception):
    def __init__(self, experiment_id: uuid.UUID) -> None:
        self.experiment_id = experiment_id
        super().__init__(f"Experiment not found: {experiment_id}")


@dataclass(frozen=True, slots=True)
class CreateExperimentCommand:
    project_id: uuid.UUID
    name: str
    dataset_id: uuid.UUID
    model_config: dict[str, Any] | None = None
    version: str | None = None
    baseline_experiment_id: uuid.UUID | None = None
    app_config_id: uuid.UUID | None = None
    app_config_alias: str | None = None
    metrics_set_id: uuid.UUID | None = None


class CreateExperiment:
    def __init__(
        self,
        experiments: ExperimentRepository,
        datasets: DatasetRepository,
        projects: ProjectRepository,
        app_configs: AppConfigRepository,
        metrics_sets: MetricsSetRepository,
    ) -> None:
        self._experiments = experiments
        self._datasets = datasets
        self._projects = projects
        self._app_configs = app_configs
        self._metrics_sets = metrics_sets

    async def execute(self, command: CreateExperimentCommand) -> Experiment:
        project = await self._projects.get_by_id(command.project_id)
        if project is None:
            raise ProjectNotFoundError(command.project_id)
        dataset = await self._datasets.get_by_id(command.dataset_id)
        if dataset is None:
            raise DatasetNotFoundError(command.dataset_id)
        if dataset.project_id != command.project_id:
            raise DatasetNotFoundError(command.dataset_id)
        if command.baseline_experiment_id is not None:
            baseline = await self._experiments.get_by_id(command.baseline_experiment_id)
            if baseline is None or baseline.project_id != command.project_id:
                raise ExperimentNotFoundError(command.baseline_experiment_id)

        if command.app_config_id is not None and command.app_config_alias is not None:
            raise ValueError("Provide only one of app_config_id or app_config_alias")

        config: AppConfig | None = None
        if command.app_config_alias is not None:
            alias_name = command.app_config_alias.strip()
            if not alias_name:
                raise ValueError("app_config_alias must not be empty")
            alias = await self._app_configs.get_alias(command.project_id, alias_name)
            if alias is None:
                raise ValueError(f"Unknown app_config_alias: {alias_name}")
            config = await self._app_configs.get_by_id(alias.app_config_id)
            if config is None or config.project_id != command.project_id:
                raise AppConfigNotFoundError(alias.app_config_id)
        elif command.app_config_id is not None:
            config = await self._app_configs.get_by_id(command.app_config_id)
            if config is None or config.project_id != command.project_id:
                raise AppConfigNotFoundError(command.app_config_id)

        model_config = command.model_config
        app_config_id = None
        if config is not None:
            model_config = config.to_snapshot()
            app_config_id = config.id

        metrics_set_id = command.metrics_set_id
        if metrics_set_id is not None:
            metrics_set = await self._metrics_sets.get_by_id(metrics_set_id)
            if metrics_set is None or metrics_set.project_id != command.project_id:
                raise MetricsSetNotFoundError(metrics_set_id)

        experiment = Experiment.create(
            command.project_id,
            command.name,
            command.dataset_id,
            model_config=model_config,
            version=command.version,
            baseline_experiment_id=command.baseline_experiment_id,
            app_config_id=app_config_id,
            metrics_set_id=metrics_set_id,
        )
        return await self._experiments.add(experiment)


class ListExperiments:
    def __init__(self, experiments: ExperimentRepository) -> None:
        self._experiments = experiments

    async def execute(self, project_id: uuid.UUID) -> list[Experiment]:
        return await self._experiments.list_by_project(project_id)


class GetExperiment:
    def __init__(self, experiments: ExperimentRepository) -> None:
        self._experiments = experiments

    async def execute(self, experiment_id: uuid.UUID) -> Experiment:
        experiment = await self._experiments.get_by_id(experiment_id)
        if experiment is None:
            raise ExperimentNotFoundError(experiment_id)
        return experiment
