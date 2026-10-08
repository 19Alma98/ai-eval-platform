from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

from aiobs.application.evaluators import (
    CreateEvaluator,
    CreateEvaluatorCommand,
    EvaluatorConflictError,
)
from aiobs.application.projects import ProjectNotFoundError
from aiobs.domain.evaluator import Evaluator
from aiobs.domain.experiment import Experiment
from aiobs.domain.metrics_set import (
    _UNSET,
    DEFAULT_RAG_SET_ENTRIES,
    MetricsSet,
    MetricsSetEntry,
    assert_unique_evaluator_ids,
)
from aiobs.domain.repositories import (
    EvaluatorRepository,
    ExperimentRepository,
    MetricsSetRepository,
    ProjectRepository,
)

_LLM_JUDGE_KINDS = frozenset(
    {"groundedness", "correctness", "answer_relevance", "context_precision"}
)


class MetricsSetNotFoundError(Exception):
    def __init__(self, metrics_set_id: uuid.UUID) -> None:
        self.metrics_set_id = metrics_set_id
        super().__init__(f"Metrics set not found: {metrics_set_id}")


class MetricsSetEntryNotFoundError(Exception):
    def __init__(self, metrics_set_id: uuid.UUID, entry_id: uuid.UUID) -> None:
        self.metrics_set_id = metrics_set_id
        self.entry_id = entry_id
        super().__init__(f"Metrics set entry not found: {entry_id} in metrics set {metrics_set_id}")


class MetricsSetConflictError(Exception):
    def __init__(self, name: str, version: int) -> None:
        self.name = name
        self.version = version
        super().__init__(f"Metrics set already exists: {name} v{version}")


class MetricsSetReferencedError(Exception):
    def __init__(self, metrics_set_id: uuid.UUID) -> None:
        self.metrics_set_id = metrics_set_id
        super().__init__(f"Metrics set is referenced by experiments: {metrics_set_id}")


class MetricsSetProtectedError(Exception):
    pass


class MetricsSetValidationError(Exception):
    pass


def _evaluator_type_for_kind(kind: str) -> str:
    if kind in _LLM_JUDGE_KINDS:
        return "llm_judge"
    return "deterministic"


def _evaluator_config_for_entry(entry: MetricsSetEntry) -> dict[str, Any]:
    config = dict(entry.config)
    config["kind"] = entry.kind
    return config


async def _require_evaluator_in_project(
    evaluators: EvaluatorRepository,
    project_id: uuid.UUID,
    evaluator_id: uuid.UUID,
) -> None:
    evaluator = await evaluators.get_by_id(evaluator_id)
    if evaluator is None:
        raise MetricsSetValidationError(f"Unknown evaluator_id: {evaluator_id}")
    if evaluator.project_id != project_id:
        raise MetricsSetValidationError(f"evaluator_id does not belong to project: {evaluator_id}")


async def _evaluators_for_kind(
    evaluators: EvaluatorRepository,
    project_id: uuid.UUID,
    kind: str,
) -> list[Evaluator]:
    """Auto-managed evaluators for a kind (name == kind), lowest version first."""
    matches = [
        evaluator
        for evaluator in await evaluators.list_by_project(project_id)
        if evaluator.name == kind and str(evaluator.config.get("kind", "")).strip() == kind
    ]
    return sorted(matches, key=lambda e: e.version)


def _first_available(
    candidates: list[Evaluator], exclude: frozenset[uuid.UUID]
) -> Evaluator | None:
    return next((e for e in candidates if e.id not in exclude), None)


def _replace_entry_at(metrics_set: MetricsSet, entry: MetricsSetEntry) -> MetricsSet:
    idx = next(i for i, e in enumerate(metrics_set.entries) if e.kind == entry.kind)
    new_entries = metrics_set.entries[:idx] + (entry,) + metrics_set.entries[idx + 1 :]
    return replace(metrics_set, entries=new_entries, updated_at=metrics_set.updated_at)


async def _assert_unique_name_version(
    repo: MetricsSetRepository,
    project_id: uuid.UUID,
    name: str,
    version: int,
) -> None:
    for existing in await repo.list_by_project(project_id):
        if existing.name == name and existing.version == version:
            raise MetricsSetConflictError(name, version)


def _with_missing_default_entries(metrics_set: MetricsSet) -> MetricsSet:
    existing = {e.kind for e in metrics_set.entries}
    extras = [
        replace(default, id=uuid.uuid4(), config=dict(default.config))
        for default in DEFAULT_RAG_SET_ENTRIES
        if default.kind not in existing
    ]
    if not extras:
        return metrics_set
    return replace(
        metrics_set,
        entries=(*metrics_set.entries, *extras),
        updated_at=datetime.now(UTC),
    )


async def find_or_create_evaluator_for_entry(
    evaluators: EvaluatorRepository,
    create_evaluator: CreateEvaluator,
    project_id: uuid.UUID,
    entry: MetricsSetEntry,
    *,
    exclude: frozenset[uuid.UUID] = frozenset(),
) -> Evaluator:
    """Reuse the project's evaluator for this kind, creating it if missing.

    ``exclude`` holds evaluators already backing other entries of the same metrics
    set: an entry must get its own evaluator (see ``assert_unique_evaluator_ids``),
    so when the kind's evaluator is taken a new version is created.

    Concurrent callers (e.g. parallel live-scoring tasks) can both miss on find and
    race on create; the loser hits the unique constraint and re-reads the winner's row.
    """
    candidates = await _evaluators_for_kind(evaluators, project_id, entry.kind)
    evaluator = _first_available(candidates, exclude)
    if evaluator is not None:
        return evaluator
    next_version = max((e.version for e in candidates), default=0) + 1
    try:
        return await create_evaluator.execute(
            CreateEvaluatorCommand(
                project_id=project_id,
                name=entry.kind,
                type=_evaluator_type_for_kind(entry.kind),
                config=_evaluator_config_for_entry(entry),
                version=next_version,
            )
        )
    except EvaluatorConflictError:
        candidates = await _evaluators_for_kind(evaluators, project_id, entry.kind)
        evaluator = _first_available(candidates, exclude)
        if evaluator is None:
            raise
        return evaluator


def _evaluator_ids_in_use(entries: tuple[MetricsSetEntry, ...]) -> frozenset[uuid.UUID]:
    return frozenset(e.evaluator_id for e in entries if e.evaluator_id is not None)


async def _ensure_entry_evaluator_ids(
    metrics_set: MetricsSet,
    evaluators: EvaluatorRepository,
    create_evaluator: CreateEvaluator,
    *,
    only_enabled: bool,
) -> MetricsSet:
    current = metrics_set
    for entry in metrics_set.entries:
        if entry.evaluator_id is not None or (only_enabled and not entry.enabled):
            continue
        evaluator = await find_or_create_evaluator_for_entry(
            evaluators,
            create_evaluator,
            metrics_set.project_id,
            entry,
            exclude=_evaluator_ids_in_use(current.entries),
        )
        idx = next(i for i, e in enumerate(current.entries) if e.kind == entry.kind)
        current_entry = current.entries[idx]
        current = _replace_entry_at(current, replace(current_entry, evaluator_id=evaluator.id))
    return current


def _apply_entry_input(
    metrics_set: MetricsSet,
    existing: MetricsSetEntry,
    inp: MetricsSetEntryInput,
) -> MetricsSet:
    merged_config = dict(existing.config)
    merged_config.update(dict(inp.config))
    merged_config.pop("kind", None)
    updated = metrics_set.patch_entry(
        existing.kind,
        enabled=inp.enabled,
        threshold=inp.threshold,
        config=merged_config,
    )
    if inp.evaluator_id is not None:
        updated = updated.patch_entry(existing.kind, evaluator_id=inp.evaluator_id)
    return updated


async def _apply_entry_replacement(
    metrics_set: MetricsSet,
    entries: list[MetricsSetEntryInput],
    evaluators: EvaluatorRepository,
    *,
    protect_is_default: bool,
) -> MetricsSet:
    for inp in entries:
        if inp.evaluator_id is not None:
            await _require_evaluator_in_project(
                evaluators, metrics_set.project_id, inp.evaluator_id
            )

    incoming_by_kind = {inp.kind.strip(): inp for inp in entries}
    if len(incoming_by_kind) != len(entries):
        raise MetricsSetValidationError("duplicate metrics set entry kinds")

    if protect_is_default:
        for existing in metrics_set.entries:
            if existing.is_default and existing.kind not in incoming_by_kind:
                raise MetricsSetProtectedError(
                    f"cannot remove is_default metrics set entry: {existing.kind}"
                )

    updated = metrics_set
    original_kinds = {e.kind for e in metrics_set.entries}
    for existing in metrics_set.entries:
        patch = incoming_by_kind.get(existing.kind)
        if patch is not None:
            updated = _apply_entry_input(updated, existing, patch)

    for inp in entries:
        kind = inp.kind.strip()
        if kind in original_kinds:
            continue
        if inp.evaluator_id is None:
            raise MetricsSetValidationError(
                f"custom metrics set entry requires evaluator_id: {kind}"
            )
        new_entry = MetricsSetEntry(
            id=uuid.uuid4(),
            kind=kind,
            enabled=inp.enabled,
            threshold=inp.threshold,
            config=dict(inp.config),
            evaluator_id=inp.evaluator_id,
            is_default=False,
        )
        updated = updated.append_entry(new_entry)

    incoming_kinds = set(incoming_by_kind.keys())
    for existing in metrics_set.entries:
        if existing.kind in incoming_kinds or existing.is_default:
            continue
        updated = updated.remove_entry(existing.kind)

    try:
        assert_unique_evaluator_ids(updated.entries)
    except ValueError as exc:
        raise MetricsSetValidationError(str(exc)) from exc
    return updated


def _inputs_to_entries(inputs: list[MetricsSetEntryInput]) -> tuple[MetricsSetEntry, ...]:
    return tuple(
        MetricsSetEntry(
            id=uuid.uuid4(),
            kind=inp.kind.strip(),
            enabled=inp.enabled,
            threshold=inp.threshold,
            config=dict(inp.config),
            evaluator_id=inp.evaluator_id,
            is_default=False,
        )
        for inp in inputs
    )


@dataclass(frozen=True, slots=True)
class MetricsSetEntryInput:
    kind: str
    enabled: bool
    threshold: float | None
    config: dict[str, Any]
    evaluator_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class CreateMetricsSetCommand:
    project_id: uuid.UUID
    name: str
    description: str | None
    entries: list[MetricsSetEntryInput]


class EnsureProjectDefaultMetricsSet:
    def __init__(
        self,
        metrics_sets: MetricsSetRepository,
        evaluators: EvaluatorRepository,
        projects: ProjectRepository,
        create_evaluator: CreateEvaluator,
    ) -> None:
        self._metrics_sets = metrics_sets
        self._evaluators = evaluators
        self._projects = projects
        self._create_evaluator = create_evaluator

    async def execute(self, project_id: uuid.UUID) -> MetricsSet:
        project = await self._projects.get_by_id(project_id)
        if project is None:
            raise ProjectNotFoundError(project_id)

        metrics_set = await self._metrics_sets.get_project_default(project_id)
        if metrics_set is None:
            try:
                metrics_set = await self._metrics_sets.add(
                    MetricsSet.create_project_default(project_id)
                )
            except Exception:
                # A concurrent caller created the default first (one-default-per-project
                # unique index): use theirs.
                existing = await self._metrics_sets.get_project_default(project_id)
                if existing is None:
                    raise
                metrics_set = existing
        else:
            backfilled = _with_missing_default_entries(metrics_set)
            if backfilled.entries != metrics_set.entries:
                try:
                    metrics_set = await self._metrics_sets.update(backfilled)
                except Exception:
                    # A concurrent caller backfilled the same entries first.
                    existing = await self._metrics_sets.get_project_default(project_id)
                    if existing is None:
                        raise
                    metrics_set = existing

        updated = await _ensure_entry_evaluator_ids(
            metrics_set, self._evaluators, self._create_evaluator, only_enabled=False
        )
        if updated.entries != metrics_set.entries:
            return await self._metrics_sets.update(updated)
        return metrics_set


class ListMetricsSets:
    def __init__(
        self,
        metrics_sets: MetricsSetRepository,
        projects: ProjectRepository,
    ) -> None:
        self._metrics_sets = metrics_sets
        self._projects = projects

    async def execute(self, project_id: uuid.UUID) -> list[MetricsSet]:
        project = await self._projects.get_by_id(project_id)
        if project is None:
            raise ProjectNotFoundError(project_id)
        return await self._metrics_sets.list_by_project(project_id)


class GetMetricsSet:
    def __init__(self, metrics_sets: MetricsSetRepository) -> None:
        self._metrics_sets = metrics_sets

    async def execute(self, metrics_set_id: uuid.UUID) -> MetricsSet:
        metrics_set = await self._metrics_sets.get_by_id(metrics_set_id)
        if metrics_set is None:
            raise MetricsSetNotFoundError(metrics_set_id)
        return metrics_set


class CreateMetricsSet:
    def __init__(
        self,
        metrics_sets: MetricsSetRepository,
        evaluators: EvaluatorRepository,
        projects: ProjectRepository,
    ) -> None:
        self._metrics_sets = metrics_sets
        self._evaluators = evaluators
        self._projects = projects

    async def execute(self, command: CreateMetricsSetCommand) -> MetricsSet:
        project = await self._projects.get_by_id(command.project_id)
        if project is None:
            raise ProjectNotFoundError(command.project_id)
        for inp in command.entries:
            if inp.evaluator_id is not None:
                await _require_evaluator_in_project(
                    self._evaluators, command.project_id, inp.evaluator_id
                )
        try:
            metrics_set = MetricsSet.create(
                command.project_id,
                command.name,
                description=command.description,
                entries=_inputs_to_entries(command.entries),
            )
        except ValueError as exc:
            raise MetricsSetValidationError(str(exc)) from exc
        await _assert_unique_name_version(
            self._metrics_sets, metrics_set.project_id, metrics_set.name, metrics_set.version
        )
        return await self._metrics_sets.add(metrics_set)


@dataclass(frozen=True, slots=True)
class PatchMetricsSetCommand:
    metrics_set_id: uuid.UUID
    name: str | None = None
    description: str | None | Any = _UNSET
    entries: list[MetricsSetEntryInput] | None = None


class PatchMetricsSet:
    def __init__(
        self,
        metrics_sets: MetricsSetRepository,
        evaluators: EvaluatorRepository,
        experiments: ExperimentRepository,
    ) -> None:
        self._metrics_sets = metrics_sets
        self._evaluators = evaluators
        self._experiments = experiments

    async def execute(self, command: PatchMetricsSetCommand) -> MetricsSet:
        metrics_set = await self._metrics_sets.get_by_id(command.metrics_set_id)
        if metrics_set is None:
            raise MetricsSetNotFoundError(command.metrics_set_id)

        if await self._experiments.count_by_metrics_set_id(metrics_set.id) > 0:
            raise MetricsSetReferencedError(metrics_set.id)

        updated = metrics_set
        if command.name is not None:
            cleaned = command.name.strip()
            if not cleaned:
                raise MetricsSetValidationError("Metrics set name must not be empty")
            updated = replace(updated, name=cleaned, updated_at=datetime.now(UTC))
        if command.description is not _UNSET:
            description = command.description.strip() if command.description else None
            updated = replace(updated, description=description, updated_at=datetime.now(UTC))

        if command.entries is not None:
            updated = await _apply_entry_replacement(
                updated,
                command.entries,
                self._evaluators,
                protect_is_default=updated.is_project_default,
            )

        return await self._metrics_sets.update(updated)


@dataclass(frozen=True, slots=True)
class VersionMetricsSetCommand:
    metrics_set_id: uuid.UUID
    description: str | None | Any = _UNSET
    entries: list[MetricsSetEntryInput] | None = None


class VersionMetricsSet:
    def __init__(
        self,
        metrics_sets: MetricsSetRepository,
        evaluators: EvaluatorRepository,
    ) -> None:
        self._metrics_sets = metrics_sets
        self._evaluators = evaluators

    async def execute(self, command: VersionMetricsSetCommand) -> MetricsSet:
        source = await self._metrics_sets.get_by_id(command.metrics_set_id)
        if source is None:
            raise MetricsSetNotFoundError(command.metrics_set_id)

        next_version = await self._metrics_sets.next_version(source.project_id, source.name)
        copy = source.copy_as_next_version(next_version)

        if command.description is not _UNSET:
            description = command.description.strip() if command.description else None
            copy = replace(copy, description=description)

        if command.entries is not None:
            copy = await _apply_entry_replacement(
                copy,
                command.entries,
                self._evaluators,
                protect_is_default=False,
            )

        await _assert_unique_name_version(
            self._metrics_sets, copy.project_id, copy.name, copy.version
        )
        return await self._metrics_sets.add(copy)


class DeleteMetricsSet:
    def __init__(
        self,
        metrics_sets: MetricsSetRepository,
        experiments: ExperimentRepository,
    ) -> None:
        self._metrics_sets = metrics_sets
        self._experiments = experiments

    async def execute(self, metrics_set_id: uuid.UUID) -> None:
        metrics_set = await self._metrics_sets.get_by_id(metrics_set_id)
        if metrics_set is None:
            raise MetricsSetNotFoundError(metrics_set_id)
        if metrics_set.is_project_default:
            raise MetricsSetProtectedError("project default metrics set cannot be deleted")
        if await self._experiments.count_by_metrics_set_id(metrics_set_id) > 0:
            raise MetricsSetReferencedError(metrics_set_id)
        await self._metrics_sets.delete(metrics_set_id)


class DeleteMetricsSetEntry:
    def __init__(
        self,
        metrics_sets: MetricsSetRepository,
        experiments: ExperimentRepository,
    ) -> None:
        self._metrics_sets = metrics_sets
        self._experiments = experiments

    async def execute(self, metrics_set_id: uuid.UUID, entry_id: uuid.UUID) -> MetricsSet:
        metrics_set = await self._metrics_sets.get_by_id(metrics_set_id)
        if metrics_set is None:
            raise MetricsSetNotFoundError(metrics_set_id)

        entry = next((e for e in metrics_set.entries if e.id == entry_id), None)
        if entry is None:
            raise MetricsSetEntryNotFoundError(metrics_set_id, entry_id)

        if entry.is_default:
            raise MetricsSetProtectedError(
                f"metrics set entry is_default cannot be deleted: {entry.kind}"
            )
        if await self._experiments.count_by_metrics_set_id(metrics_set_id) > 0:
            raise MetricsSetReferencedError(metrics_set_id)

        updated = metrics_set.remove_entry_by_id(entry_id)
        return await self._metrics_sets.update(updated)


class ResolveMetricsSetForScore:
    def __init__(
        self,
        metrics_sets: MetricsSetRepository,
        experiments: ExperimentRepository,
        evaluators: EvaluatorRepository,
        create_evaluator: CreateEvaluator,
        ensure_default: EnsureProjectDefaultMetricsSet,
    ) -> None:
        self._metrics_sets = metrics_sets
        self._experiments = experiments
        self._evaluators = evaluators
        self._create_evaluator = create_evaluator
        self._ensure_default = ensure_default

    async def execute(
        self,
        *,
        experiment: Experiment,
        metrics_set_id: uuid.UUID | None,
        save_as_default: bool,
    ) -> MetricsSet:
        request_metrics_set_id = metrics_set_id
        resolved: MetricsSet | None = None

        if metrics_set_id is not None:
            resolved = await self._load_for_experiment(metrics_set_id, experiment.project_id)
        elif experiment.metrics_set_id is not None:
            resolved = await self._load_for_experiment(
                experiment.metrics_set_id, experiment.project_id
            )
        else:
            resolved = await self._ensure_default.execute(experiment.project_id)

        with_evaluators = await _ensure_entry_evaluator_ids(
            resolved, self._evaluators, self._create_evaluator, only_enabled=True
        )
        if with_evaluators.entries != resolved.entries:
            resolved = await self._metrics_sets.update(with_evaluators)
        else:
            resolved = with_evaluators

        if save_as_default and request_metrics_set_id is not None:
            await self._experiments.update(experiment.with_metrics_set_id(resolved.id))

        return resolved

    async def _load_for_experiment(
        self, metrics_set_id: uuid.UUID, project_id: uuid.UUID
    ) -> MetricsSet:
        metrics_set = await self._metrics_sets.get_by_id(metrics_set_id)
        if metrics_set is None or metrics_set.project_id != project_id:
            raise MetricsSetNotFoundError(metrics_set_id)
        return metrics_set
