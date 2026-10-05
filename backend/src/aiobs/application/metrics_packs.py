from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from typing import Any

from aiobs.application.evaluators import CreateEvaluator, CreateEvaluatorCommand
from aiobs.application.projects import ProjectNotFoundError
from aiobs.domain.metrics_pack import (
    DEFAULT_RAG_ENTRIES,
    MetricsPack,
    MetricsPackEntry,
)
from aiobs.domain.repositories import (
    EvaluatorRepository,
    MetricsPackRepository,
    ProjectRepository,
)

_LLM_JUDGE_KINDS = frozenset({"groundedness", "correctness", "answer_relevance"})


class MetricsPackNotFoundError(Exception):
    def __init__(self, project_id: uuid.UUID) -> None:
        self.project_id = project_id
        super().__init__(f"Metrics pack not found for project: {project_id}")


class MetricsPackValidationError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class MetricsPackEntryPatch:
    kind: str
    enabled: bool
    threshold: float | None
    config: dict[str, Any]
    evaluator_id: uuid.UUID | None = None
    removable: bool | None = None


def _evaluator_type_for_kind(kind: str) -> str:
    if kind in _LLM_JUDGE_KINDS:
        return "llm_judge"
    return "deterministic"


def _evaluator_config_for_entry(entry: MetricsPackEntry) -> dict[str, Any]:
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
        raise ValueError(f"Unknown evaluator_id: {evaluator_id}")
    if evaluator.project_id != project_id:
        raise ValueError(f"evaluator_id does not belong to project: {evaluator_id}")


async def _find_evaluator_by_kind(
    evaluators: EvaluatorRepository,
    project_id: uuid.UUID,
    kind: str,
):
    for evaluator in await evaluators.list_by_project(project_id):
        if evaluator.name == kind and str(evaluator.config.get("kind", "")).strip() == kind:
            return evaluator
    return None


def _replace_entry_at(pack: MetricsPack, entry: MetricsPackEntry) -> MetricsPack:
    idx = next(i for i, e in enumerate(pack.entries) if e.kind == entry.kind)
    new_entries = pack.entries[:idx] + (entry,) + pack.entries[idx + 1 :]
    return replace(pack, entries=new_entries, updated_at=pack.updated_at)


def _apply_patch(
    pack: MetricsPack,
    existing: MetricsPackEntry,
    patch: MetricsPackEntryPatch,
) -> MetricsPack:
    merged_config = dict(existing.config)
    merged_config.update(dict(patch.config))
    merged_config.pop("kind", None)
    updated = pack.patch_entry(
        existing.kind,
        enabled=patch.enabled,
        threshold=patch.threshold,
        config=merged_config,
    )
    if patch.evaluator_id is not None:
        idx = next(i for i, e in enumerate(updated.entries) if e.kind == existing.kind)
        entry = updated.entries[idx]
        updated = _replace_entry_at(updated, replace(entry, evaluator_id=patch.evaluator_id))
    return updated


class EnsureMetricsPack:
    def __init__(
        self,
        packs: MetricsPackRepository,
        evaluators: EvaluatorRepository,
        projects: ProjectRepository,
        create_evaluator: CreateEvaluator,
    ) -> None:
        self._packs = packs
        self._evaluators = evaluators
        self._projects = projects
        self._create_evaluator = create_evaluator

    async def execute(self, project_id: uuid.UUID) -> MetricsPack:
        project = await self._projects.get_by_id(project_id)
        if project is None:
            raise ProjectNotFoundError(project_id)

        pack = await self._packs.get_by_project_id(project_id)
        if pack is None:
            pack = await self._packs.add(MetricsPack.create(project_id))

        updated = await self._ensure_evaluator_ids(pack)
        if updated.entries != pack.entries:
            return await self._packs.update(updated)
        return pack

    async def _ensure_evaluator_ids(self, pack: MetricsPack) -> MetricsPack:
        current = pack
        for entry in pack.entries:
            if entry.evaluator_id is not None:
                continue
            evaluator = await _find_evaluator_by_kind(
                self._evaluators, pack.project_id, entry.kind
            )
            if evaluator is None:
                evaluator = await self._create_evaluator.execute(
                    CreateEvaluatorCommand(
                        project_id=pack.project_id,
                        name=entry.kind,
                        type=_evaluator_type_for_kind(entry.kind),
                        config=_evaluator_config_for_entry(entry),
                    )
                )
            idx = next(i for i, e in enumerate(current.entries) if e.kind == entry.kind)
            current_entry = current.entries[idx]
            current = _replace_entry_at(
                current, replace(current_entry, evaluator_id=evaluator.id)
            )
        return current


class GetMetricsPack:
    def __init__(self, packs: MetricsPackRepository) -> None:
        self._packs = packs

    async def execute(self, project_id: uuid.UUID) -> MetricsPack:
        pack = await self._packs.get_by_project_id(project_id)
        if pack is None:
            raise MetricsPackNotFoundError(project_id)
        return pack


class ReplaceMetricsPack:
    def __init__(
        self,
        packs: MetricsPackRepository,
        evaluators: EvaluatorRepository,
    ) -> None:
        self._packs = packs
        self._evaluators = evaluators

    async def execute(
        self,
        project_id: uuid.UUID,
        entries: list[MetricsPackEntryPatch],
    ) -> MetricsPack:
        pack = await self._packs.get_by_project_id(project_id)
        if pack is None:
            raise MetricsPackNotFoundError(project_id)

        for patch in entries:
            if patch.evaluator_id is not None:
                await _require_evaluator_in_project(
                    self._evaluators, project_id, patch.evaluator_id
                )

        incoming_by_kind = {e.kind.strip(): e for e in entries}
        if len(incoming_by_kind) != len(entries):
            raise MetricsPackValidationError("duplicate metrics pack entry kinds")

        for default in DEFAULT_RAG_ENTRIES:
            if default.kind not in incoming_by_kind:
                raise MetricsPackValidationError(
                    f"cannot remove required metrics pack entry: {default.kind}"
                )

        updated = pack
        original_kinds = {e.kind for e in pack.entries}
        for existing in pack.entries:
            patch = incoming_by_kind.get(existing.kind)
            if patch is None:
                if not existing.removable:
                    raise MetricsPackValidationError(
                        f"cannot remove required metrics pack entry: {existing.kind}"
                    )
                updated = updated.remove_entry(existing.kind)
                continue
            updated = _apply_patch(updated, existing, patch)

        for patch in entries:
            if patch.kind.strip() in original_kinds:
                continue
            if patch.removable is not True:
                raise MetricsPackValidationError(
                    f"new metrics pack entry must have removable=True: {patch.kind}"
                )
            if patch.evaluator_id is None:
                raise MetricsPackValidationError(
                    f"custom metrics pack entry requires evaluator_id: {patch.kind}"
                )
            new_entry = MetricsPackEntry(
                kind=patch.kind.strip(),
                enabled=patch.enabled,
                threshold=patch.threshold,
                config=dict(patch.config),
                evaluator_id=patch.evaluator_id,
                removable=True,
            )
            updated = updated.append_entry(new_entry)

        return await self._packs.update(updated)


class PatchMetricsPack:
    def __init__(self, packs: MetricsPackRepository) -> None:
        self._packs = packs

    async def execute(
        self,
        project_id: uuid.UUID,
        patches: list[MetricsPackEntryPatch],
    ) -> MetricsPack:
        pack = await self._packs.get_by_project_id(project_id)
        if pack is None:
            raise MetricsPackNotFoundError(project_id)

        updated = pack
        known_kinds = {e.kind for e in pack.entries}
        for patch in patches:
            cleaned = patch.kind.strip()
            if cleaned in known_kinds:
                existing = next(e for e in updated.entries if e.kind == cleaned)
                updated = _apply_patch(updated, existing, patch)
                continue
            if patch.removable is not True:
                raise MetricsPackValidationError(
                    f"new metrics pack entry must have removable=True: {cleaned}"
                )
            if patch.evaluator_id is None:
                raise MetricsPackValidationError(
                    f"custom metrics pack entry requires evaluator_id: {cleaned}"
                )
            new_entry = MetricsPackEntry(
                kind=cleaned,
                enabled=patch.enabled,
                threshold=patch.threshold,
                config=dict(patch.config),
                evaluator_id=patch.evaluator_id,
                removable=True,
            )
            updated = updated.append_entry(new_entry)
            known_kinds.add(cleaned)

        return await self._packs.update(updated)
