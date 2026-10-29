from __future__ import annotations

import uuid
from dataclasses import dataclass

from opengrade_server.application.experiments import ExperimentNotFoundError
from opengrade_server.application.projects import ProjectNotFoundError
from opengrade_server.domain.experiment import Experiment
from opengrade_server.domain.experiment_alias import (
    ExperimentAlias,
    ExperimentAliasEvent,
    clean_alias_name,
)
from opengrade_server.domain.repositories import (
    ExperimentAliasRepository,
    ExperimentRepository,
    ProjectRepository,
)

UNPROMOTABLE_STATUSES = frozenset({"running", "failed", "cancelled"})


class ExperimentAliasNotFoundError(Exception):
    def __init__(self, project_id: uuid.UUID, alias: str) -> None:
        self.project_id = project_id
        self.alias = alias
        super().__init__(f"Experiment alias not found: {alias} in project {project_id}")


class ExperimentNotPromotableError(Exception):
    def __init__(self, experiment_id: uuid.UUID, status: str) -> None:
        self.experiment_id = experiment_id
        self.status = status
        super().__init__(
            f"Experiment {experiment_id} is {status!r}; a running, failed or cancelled "
            "experiment cannot be set as an alias"
        )


class ExperimentAliasExamMismatchError(Exception):
    def __init__(self, alias: str, current: Experiment, candidate: Experiment) -> None:
        self.alias = alias
        changed = []
        if current.dataset_id != candidate.dataset_id:
            changed.append("dataset")
        if current.metrics_set_id != candidate.metrics_set_id:
            changed.append("metrics set")
        super().__init__(
            f"Alias {alias!r} points to experiment {current.id} with a different "
            f"{' and '.join(changed)}; pass force=true to move it anyway"
        )


def same_exam(a: Experiment, b: Experiment) -> bool:
    return a.dataset_id == b.dataset_id and a.metrics_set_id == b.metrics_set_id


@dataclass(frozen=True, slots=True)
class SetExperimentAliasCommand:
    project_id: uuid.UUID
    alias: str
    experiment_id: uuid.UUID
    note: str | None = None
    force: bool = False


@dataclass(frozen=True, slots=True)
class ExperimentAliasWithExperiment:
    alias: ExperimentAlias
    experiment: Experiment


@dataclass(frozen=True, slots=True)
class SetExperimentAliasResult:
    alias: ExperimentAlias
    experiment: Experiment
    previous_experiment_id: uuid.UUID | None
    changed: bool


async def _require_project(projects: ProjectRepository, project_id: uuid.UUID) -> None:
    if await projects.get_by_id(project_id) is None:
        raise ProjectNotFoundError(project_id)


async def _experiment_in_project(
    experiments: ExperimentRepository, project_id: uuid.UUID, experiment_id: uuid.UUID
) -> Experiment:
    experiment = await experiments.get_by_id(experiment_id)
    if experiment is None or experiment.project_id != project_id:
        raise ExperimentNotFoundError(experiment_id)
    return experiment


class SetExperimentAlias:
    def __init__(
        self,
        aliases: ExperimentAliasRepository,
        experiments: ExperimentRepository,
        projects: ProjectRepository,
    ) -> None:
        self._aliases = aliases
        self._experiments = experiments
        self._projects = projects

    async def execute(self, command: SetExperimentAliasCommand) -> SetExperimentAliasResult:
        await _require_project(self._projects, command.project_id)
        name = clean_alias_name(command.alias)
        candidate = await _experiment_in_project(
            self._experiments, command.project_id, command.experiment_id
        )
        if candidate.status in UNPROMOTABLE_STATUSES:
            raise ExperimentNotPromotableError(candidate.id, candidate.status)

        current = await self._aliases.get(command.project_id, name)
        if current is not None and current.experiment_id == candidate.id:
            return SetExperimentAliasResult(
                alias=current,
                experiment=candidate,
                previous_experiment_id=current.experiment_id,
                changed=False,
            )
        if current is not None and not command.force:
            target = await self._experiments.get_by_id(current.experiment_id)
            if target is not None and not same_exam(target, candidate):
                raise ExperimentAliasExamMismatchError(name, target, candidate)

        alias = ExperimentAlias.create(command.project_id, name, candidate.id)
        previous_id = current.experiment_id if current is not None else None
        event = ExperimentAliasEvent.create(
            alias, previous_experiment_id=previous_id, note=command.note
        )
        saved = await self._aliases.set(alias, event)
        return SetExperimentAliasResult(
            alias=saved,
            experiment=candidate,
            previous_experiment_id=previous_id,
            changed=True,
        )


class GetExperimentAlias:
    def __init__(
        self,
        aliases: ExperimentAliasRepository,
        experiments: ExperimentRepository,
        projects: ProjectRepository,
    ) -> None:
        self._aliases = aliases
        self._experiments = experiments
        self._projects = projects

    async def execute(self, project_id: uuid.UUID, alias: str) -> ExperimentAliasWithExperiment:
        await _require_project(self._projects, project_id)
        name = alias.strip()
        row = await self._aliases.get(project_id, name)
        if row is None:
            raise ExperimentAliasNotFoundError(project_id, name)
        experiment = await _experiment_in_project(self._experiments, project_id, row.experiment_id)
        return ExperimentAliasWithExperiment(alias=row, experiment=experiment)


class ListExperimentAliases:
    def __init__(
        self,
        aliases: ExperimentAliasRepository,
        experiments: ExperimentRepository,
        projects: ProjectRepository,
    ) -> None:
        self._aliases = aliases
        self._experiments = experiments
        self._projects = projects

    async def execute(self, project_id: uuid.UUID) -> list[ExperimentAliasWithExperiment]:
        await _require_project(self._projects, project_id)
        result: list[ExperimentAliasWithExperiment] = []
        for row in await self._aliases.list_by_project(project_id):
            experiment = await _experiment_in_project(
                self._experiments, project_id, row.experiment_id
            )
            result.append(ExperimentAliasWithExperiment(alias=row, experiment=experiment))
        return result


class ListExperimentAliasHistory:
    def __init__(self, aliases: ExperimentAliasRepository, projects: ProjectRepository) -> None:
        self._aliases = aliases
        self._projects = projects

    async def execute(
        self, project_id: uuid.UUID, alias: str, *, limit: int = 50
    ) -> list[ExperimentAliasEvent]:
        await _require_project(self._projects, project_id)
        return await self._aliases.list_events(project_id, alias.strip(), limit=limit)


class DeleteExperimentAlias:
    def __init__(self, aliases: ExperimentAliasRepository) -> None:
        self._aliases = aliases

    async def execute(self, project_id: uuid.UUID, alias: str) -> None:
        name = alias.strip()
        if not await self._aliases.delete(project_id, name):
            raise ExperimentAliasNotFoundError(project_id, name)
