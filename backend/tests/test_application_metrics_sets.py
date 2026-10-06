from __future__ import annotations

import uuid
from dataclasses import dataclass, field

import pytest

from aiobs.application.evaluators import CreateEvaluatorCommand
from aiobs.application.metrics_sets import (
    CreateMetricsSet,
    CreateMetricsSetCommand,
    DeleteMetricsSet,
    DeleteMetricsSetEntry,
    EnsureProjectDefaultMetricsSet,
    MetricsSetEntryInput,
    MetricsSetEntryNotFoundError,
    MetricsSetNotFoundError,
    MetricsSetProtectedError,
    MetricsSetReferencedError,
    PatchMetricsSet,
    PatchMetricsSetCommand,
    ResolveMetricsSetForScore,
    VersionMetricsSet,
    VersionMetricsSetCommand,
)
from aiobs.application.projects import ProjectNotFoundError
from aiobs.domain.evaluator import Evaluator
from aiobs.domain.experiment import Experiment
from aiobs.domain.project import Project
from aiobs.evaluation.deterministic import register_deterministic_evaluators
from aiobs.evaluation.registry import clear_registry
from tests.support.repositories import InMemoryEvaluatorRepository, InMemoryMetricsSetRepository


@dataclass
class InMemoryProjectRepository:
    projects: dict[uuid.UUID, Project] = field(default_factory=dict)

    async def add(self, project: Project) -> Project:
        self.projects[project.id] = project
        return project

    async def get_by_id(self, project_id: uuid.UUID) -> Project | None:
        return self.projects.get(project_id)

    async def get_by_slug(self, slug: str) -> Project | None:
        return next((p for p in self.projects.values() if p.slug == slug), None)

    async def list_all(self) -> list[Project]:
        return list(self.projects.values())


@dataclass
class InMemoryExperimentRepository:
    experiments: dict[uuid.UUID, Experiment] = field(default_factory=dict)

    async def add(self, experiment: Experiment) -> Experiment:
        self.experiments[experiment.id] = experiment
        return experiment

    async def get_by_id(self, experiment_id: uuid.UUID) -> Experiment | None:
        return self.experiments.get(experiment_id)

    async def list_by_project(self, project_id: uuid.UUID) -> list[Experiment]:
        return [e for e in self.experiments.values() if e.project_id == project_id]

    async def update(self, experiment: Experiment) -> Experiment:
        self.experiments[experiment.id] = experiment
        return experiment

    async def count_by_metrics_set_id(self, metrics_set_id: uuid.UUID) -> int:
        return sum(1 for e in self.experiments.values() if e.metrics_set_id == metrics_set_id)


@dataclass
class StubCreateEvaluator:
    evaluators: InMemoryEvaluatorRepository

    async def execute(self, command: CreateEvaluatorCommand):
        from aiobs.domain.evaluator import Evaluator

        evaluator = Evaluator.create(
            command.project_id,
            command.name,
            command.type,
            command.config,
            version=command.version,
        )
        return await self.evaluators.add(evaluator)


@pytest.fixture(autouse=True)
def _evaluator_registry() -> None:
    clear_registry()
    register_deterministic_evaluators()


async def _seed_project(
    projects: InMemoryProjectRepository,
) -> Project:
    project = Project.create("Demo")
    await projects.add(project)
    return project


@pytest.mark.asyncio
async def test_ensure_creates_default_v1_with_evaluator_ids() -> None:
    projects = InMemoryProjectRepository()
    project = await _seed_project(projects)
    sets = InMemoryMetricsSetRepository()
    evaluators = InMemoryEvaluatorRepository()
    create_eval = StubCreateEvaluator(evaluators)

    result = await EnsureProjectDefaultMetricsSet(sets, evaluators, projects, create_eval).execute(
        project.id
    )

    assert result.name == "Default"
    assert result.version == 1
    assert result.is_project_default is True
    assert all(e.evaluator_id is not None for e in result.entries)
    assert await sets.get_project_default(project.id) is not None


@pytest.mark.asyncio
async def test_ensure_raises_when_project_missing() -> None:
    projects = InMemoryProjectRepository()
    with pytest.raises(ProjectNotFoundError):
        await EnsureProjectDefaultMetricsSet(
            InMemoryMetricsSetRepository(),
            InMemoryEvaluatorRepository(),
            projects,
            StubCreateEvaluator(InMemoryEvaluatorRepository()),
        ).execute(uuid.uuid4())


@pytest.mark.asyncio
async def test_create_custom_does_not_steal_project_default() -> None:
    projects = InMemoryProjectRepository()
    project = await _seed_project(projects)
    sets = InMemoryMetricsSetRepository()
    evaluators = InMemoryEvaluatorRepository()
    create_eval = StubCreateEvaluator(evaluators)
    default = await EnsureProjectDefaultMetricsSet(sets, evaluators, projects, create_eval).execute(
        project.id
    )

    ev = await evaluators.add(
        Evaluator.create(project.id, "hit_at_k", "deterministic", {"kind": "hit_at_k", "k": 5})
    )
    custom = await CreateMetricsSet(sets, evaluators, projects).execute(
        CreateMetricsSetCommand(
            project_id=project.id,
            name="Custom",
            description=None,
            entries=[
                MetricsSetEntryInput(
                    kind="hit_at_k",
                    enabled=True,
                    threshold=0.9,
                    config={"k": 3},
                    evaluator_id=ev.id,
                )
            ],
        )
    )

    assert custom.is_project_default is False
    still_default = await sets.get_project_default(project.id)
    assert still_default is not None
    assert still_default.id == default.id


@pytest.mark.asyncio
async def test_patch_referenced_set_raises() -> None:
    projects = InMemoryProjectRepository()
    project = await _seed_project(projects)
    sets = InMemoryMetricsSetRepository()
    evaluators = InMemoryEvaluatorRepository()
    create_eval = StubCreateEvaluator(evaluators)
    metrics_set = await EnsureProjectDefaultMetricsSet(
        sets, evaluators, projects, create_eval
    ).execute(project.id)
    experiments = InMemoryExperimentRepository()
    exp = Experiment.create(project.id, "run", uuid.uuid4(), metrics_set_id=metrics_set.id)
    await experiments.add(exp)

    with pytest.raises(MetricsSetReferencedError):
        await PatchMetricsSet(sets, evaluators, experiments).execute(
            PatchMetricsSetCommand(metrics_set_id=metrics_set.id, name="Renamed")
        )


@pytest.mark.asyncio
async def test_version_bump_clears_default_flags() -> None:
    projects = InMemoryProjectRepository()
    project = await _seed_project(projects)
    sets = InMemoryMetricsSetRepository()
    evaluators = InMemoryEvaluatorRepository()
    create_eval = StubCreateEvaluator(evaluators)
    source = await EnsureProjectDefaultMetricsSet(sets, evaluators, projects, create_eval).execute(
        project.id
    )

    v2 = await VersionMetricsSet(sets, evaluators).execute(
        VersionMetricsSetCommand(metrics_set_id=source.id)
    )

    assert v2.version == 2
    assert v2.is_project_default is False
    assert all(not e.is_default for e in v2.entries)
    unchanged = await sets.get_by_id(source.id)
    assert unchanged is not None
    assert unchanged.is_project_default is True
    assert unchanged.version == 1


@pytest.mark.asyncio
async def test_delete_project_default_raises() -> None:
    projects = InMemoryProjectRepository()
    project = await _seed_project(projects)
    sets = InMemoryMetricsSetRepository()
    evaluators = InMemoryEvaluatorRepository()
    create_eval = StubCreateEvaluator(evaluators)
    metrics_set = await EnsureProjectDefaultMetricsSet(
        sets, evaluators, projects, create_eval
    ).execute(project.id)

    with pytest.raises(MetricsSetProtectedError):
        await DeleteMetricsSet(sets, InMemoryExperimentRepository()).execute(metrics_set.id)


@pytest.mark.asyncio
async def test_delete_is_default_entry_raises() -> None:
    projects = InMemoryProjectRepository()
    project = await _seed_project(projects)
    sets = InMemoryMetricsSetRepository()
    evaluators = InMemoryEvaluatorRepository()
    create_eval = StubCreateEvaluator(evaluators)
    metrics_set = await EnsureProjectDefaultMetricsSet(
        sets, evaluators, projects, create_eval
    ).execute(project.id)
    entry_id = next(e.id for e in metrics_set.entries if e.kind == "hit_at_k")

    with pytest.raises(MetricsSetProtectedError):
        await DeleteMetricsSetEntry(sets, InMemoryExperimentRepository()).execute(
            metrics_set.id, entry_id
        )


@pytest.mark.asyncio
async def test_delete_missing_entry_raises_entry_not_found() -> None:
    projects = InMemoryProjectRepository()
    project = await _seed_project(projects)
    sets = InMemoryMetricsSetRepository()
    evaluators = InMemoryEvaluatorRepository()
    create_eval = StubCreateEvaluator(evaluators)
    metrics_set = await EnsureProjectDefaultMetricsSet(
        sets, evaluators, projects, create_eval
    ).execute(project.id)
    missing_entry = uuid.uuid4()

    with pytest.raises(MetricsSetEntryNotFoundError) as exc_info:
        await DeleteMetricsSetEntry(sets, InMemoryExperimentRepository()).execute(
            metrics_set.id, missing_entry
        )
    assert exc_info.value.entry_id == missing_entry


@pytest.mark.asyncio
async def test_resolve_prefers_body_then_experiment_then_project_default() -> None:
    projects = InMemoryProjectRepository()
    project = await _seed_project(projects)
    sets = InMemoryMetricsSetRepository()
    evaluators = InMemoryEvaluatorRepository()
    create_eval = StubCreateEvaluator(evaluators)
    default = await EnsureProjectDefaultMetricsSet(sets, evaluators, projects, create_eval).execute(
        project.id
    )

    ev = await evaluators.add(
        Evaluator.create(project.id, "hit_at_k", "deterministic", {"kind": "hit_at_k", "k": 5})
    )
    custom = await CreateMetricsSet(sets, evaluators, projects).execute(
        CreateMetricsSetCommand(
            project_id=project.id,
            name="Alt",
            description=None,
            entries=[
                MetricsSetEntryInput(
                    kind="hit_at_k",
                    enabled=True,
                    threshold=0.5,
                    config={"k": 1},
                    evaluator_id=ev.id,
                )
            ],
        )
    )

    experiment = Experiment.create(project.id, "run", uuid.uuid4(), metrics_set_id=custom.id)
    experiments = InMemoryExperimentRepository()
    await experiments.add(experiment)

    resolve = ResolveMetricsSetForScore(
        sets,
        experiments,
        evaluators,
        create_eval,
        EnsureProjectDefaultMetricsSet(sets, evaluators, projects, create_eval),
    )

    from_body = await resolve.execute(
        experiment=experiment, metrics_set_id=default.id, save_as_default=False
    )
    assert from_body.id == default.id

    from_experiment = await resolve.execute(
        experiment=experiment, metrics_set_id=None, save_as_default=False
    )
    assert from_experiment.id == custom.id

    experiment_no_pin = Experiment.create(project.id, "run2", uuid.uuid4())
    await experiments.add(experiment_no_pin)
    from_default = await resolve.execute(
        experiment=experiment_no_pin, metrics_set_id=None, save_as_default=False
    )
    assert from_default.id == default.id


@pytest.mark.asyncio
async def test_save_as_default_persists_experiment_when_body_set_id() -> None:
    projects = InMemoryProjectRepository()
    project = await _seed_project(projects)
    sets = InMemoryMetricsSetRepository()
    evaluators = InMemoryEvaluatorRepository()
    create_eval = StubCreateEvaluator(evaluators)
    await EnsureProjectDefaultMetricsSet(sets, evaluators, projects, create_eval).execute(
        project.id
    )

    ev = await evaluators.add(
        Evaluator.create(project.id, "hit_at_k", "deterministic", {"kind": "hit_at_k", "k": 5})
    )
    custom = await CreateMetricsSet(sets, evaluators, projects).execute(
        CreateMetricsSetCommand(
            project_id=project.id,
            name="Pinned",
            description=None,
            entries=[
                MetricsSetEntryInput(
                    kind="hit_at_k",
                    enabled=True,
                    threshold=0.5,
                    config={"k": 1},
                    evaluator_id=ev.id,
                )
            ],
        )
    )

    experiment = Experiment.create(project.id, "run", uuid.uuid4())
    experiments = InMemoryExperimentRepository()
    await experiments.add(experiment)
    ensure = EnsureProjectDefaultMetricsSet(sets, evaluators, projects, create_eval)
    resolve = ResolveMetricsSetForScore(sets, experiments, evaluators, create_eval, ensure)

    await resolve.execute(experiment=experiment, metrics_set_id=custom.id, save_as_default=True)

    updated = await experiments.get_by_id(experiment.id)
    assert updated is not None
    assert updated.metrics_set_id == custom.id


@pytest.mark.asyncio
async def test_get_metrics_set_not_found() -> None:
    from aiobs.application.metrics_sets import GetMetricsSet

    with pytest.raises(MetricsSetNotFoundError):
        await GetMetricsSet(InMemoryMetricsSetRepository()).execute(uuid.uuid4())
