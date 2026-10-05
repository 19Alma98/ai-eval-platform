from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from typing import Any

from aiobs.application.metrics_sets import (
    EnsureProjectDefaultMetricsSet,
    MetricsSetEntryInput,
    MetricsSetProtectedError,
    MetricsSetValidationError,
    PatchMetricsSet,
    PatchMetricsSetCommand,
)
from aiobs.domain.metrics_pack import MetricsPack, MetricsPackEntry
from aiobs.domain.metrics_set import MetricsSet
from aiobs.domain.repositories import MetricsSetRepository


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


def metrics_set_to_pack(metrics_set: MetricsSet) -> MetricsPack:
    entries = tuple(
        MetricsPackEntry(
            kind=e.kind,
            enabled=e.enabled,
            threshold=e.threshold,
            config=dict(e.config),
            evaluator_id=e.evaluator_id,
            removable=not e.is_default,
        )
        for e in metrics_set.entries
    )
    return MetricsPack(
        id=metrics_set.id,
        project_id=metrics_set.project_id,
        entries=entries,
        updated_at=metrics_set.updated_at,
    )


def _pack_patch_to_set_input(patch: MetricsPackEntryPatch) -> MetricsSetEntryInput:
    return MetricsSetEntryInput(
        kind=patch.kind,
        enabled=patch.enabled,
        threshold=patch.threshold,
        config=dict(patch.config),
        evaluator_id=patch.evaluator_id,
    )


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
        updated = replace(
            updated,
            entries=updated.entries[:idx]
            + (replace(entry, evaluator_id=patch.evaluator_id),)
            + updated.entries[idx + 1 :],
        )
    return updated


class EnsureMetricsPack:
    def __init__(self, ensure_default: EnsureProjectDefaultMetricsSet) -> None:
        self._ensure_default = ensure_default

    async def execute(self, project_id: uuid.UUID) -> MetricsPack:
        metrics_set = await self._ensure_default.execute(project_id)
        return metrics_set_to_pack(metrics_set)


class GetMetricsPack:
    def __init__(self, metrics_sets: MetricsSetRepository) -> None:
        self._metrics_sets = metrics_sets

    async def execute(self, project_id: uuid.UUID) -> MetricsPack:
        metrics_set = await self._metrics_sets.get_project_default(project_id)
        if metrics_set is None:
            raise MetricsPackNotFoundError(project_id)
        return metrics_set_to_pack(metrics_set)


class ReplaceMetricsPack:
    def __init__(
        self,
        metrics_sets: MetricsSetRepository,
        patch_metrics_set: PatchMetricsSet,
    ) -> None:
        self._metrics_sets = metrics_sets
        self._patch_metrics_set = patch_metrics_set

    async def execute(
        self,
        project_id: uuid.UUID,
        entries: list[MetricsPackEntryPatch],
    ) -> MetricsPack:
        metrics_set = await self._metrics_sets.get_project_default(project_id)
        if metrics_set is None:
            raise MetricsPackNotFoundError(project_id)

        incoming_by_kind = {e.kind.strip(): e for e in entries}
        if len(incoming_by_kind) != len(entries):
            raise MetricsPackValidationError("duplicate metrics pack entry kinds")

        for existing in metrics_set.entries:
            if existing.is_default and existing.kind not in incoming_by_kind:
                raise MetricsPackValidationError(
                    f"cannot remove required metrics pack entry: {existing.kind}"
                )

        original_kinds = {e.kind for e in metrics_set.entries}
        for patch in entries:
            cleaned = patch.kind.strip()
            if cleaned in original_kinds:
                continue
            if patch.removable is not True:
                raise MetricsPackValidationError(
                    f"new metrics pack entry must have removable=True: {cleaned}"
                )
            if patch.evaluator_id is None:
                raise MetricsPackValidationError(
                    f"custom metrics pack entry requires evaluator_id: {cleaned}"
                )

        set_inputs = [_pack_patch_to_set_input(p) for p in entries]
        try:
            updated = await self._patch_metrics_set.execute(
                PatchMetricsSetCommand(
                    metrics_set_id=metrics_set.id,
                    entries=set_inputs,
                )
            )
        except MetricsSetProtectedError as exc:
            raise MetricsPackValidationError(str(exc)) from exc
        except MetricsSetValidationError as exc:
            raise MetricsPackValidationError(str(exc)) from exc

        return metrics_set_to_pack(updated)


class PatchMetricsPack:
    def __init__(
        self,
        metrics_sets: MetricsSetRepository,
        patch_metrics_set: PatchMetricsSet,
    ) -> None:
        self._metrics_sets = metrics_sets
        self._patch_metrics_set = patch_metrics_set

    async def execute(
        self,
        project_id: uuid.UUID,
        patches: list[MetricsPackEntryPatch],
    ) -> MetricsPack:
        metrics_set = await self._metrics_sets.get_project_default(project_id)
        if metrics_set is None:
            raise MetricsPackNotFoundError(project_id)

        pack = metrics_set_to_pack(metrics_set)
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

        set_inputs = [
            MetricsSetEntryInput(
                kind=e.kind,
                enabled=e.enabled,
                threshold=e.threshold,
                config=dict(e.config),
                evaluator_id=e.evaluator_id,
            )
            for e in updated.entries
        ]
        try:
            result = await self._patch_metrics_set.execute(
                PatchMetricsSetCommand(
                    metrics_set_id=metrics_set.id,
                    entries=set_inputs,
                )
            )
        except MetricsSetProtectedError as exc:
            raise MetricsPackValidationError(str(exc)) from exc
        except MetricsSetValidationError as exc:
            raise MetricsPackValidationError(str(exc)) from exc

        return metrics_set_to_pack(result)
