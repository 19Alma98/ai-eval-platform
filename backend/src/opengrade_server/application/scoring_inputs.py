from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field

from opengrade_server.application.experiment_outputs import merge_dataset_item
from opengrade_server.domain.dataset import DatasetItem
from opengrade_server.domain.experiment import Experiment
from opengrade_server.domain.experiment_output import ExperimentItemOutput
from opengrade_server.domain.repositories import DatasetRepository, ExperimentItemOutputRepository
from opengrade_server.regression.aggregate import INPUTS_FINGERPRINT_KEY

__all__ = [
    "INPUTS_FINGERPRINT_KEY",
    "CurrentScoringFingerprint",
    "ScoringInputs",
    "current_fingerprint",
    "fingerprint_items",
    "load_scoring_inputs",
]


@dataclass(frozen=True, slots=True)
class ScoringInputs:
    """One entry per (item, repeat): ``items[i]`` is scored as repeat ``repeats[i]``."""

    items: list[DatasetItem]
    missing_output_item_ids: frozenset[uuid.UUID]
    fingerprint: str
    repeats: list[int] = field(default_factory=list)


def fingerprint_items(
    items: list[DatasetItem],
    missing_output_item_ids: frozenset[uuid.UUID],
    repeats: list[int] | None = None,
) -> str:
    """Hash everything a score depends on: the gold fields and the recorded output.

    Runs keep the fingerprint they were scored with; when the test set or the
    experiment outputs change afterwards, the run no longer matches and is stale.
    """
    reps = repeats if repeats is not None else [0] * len(items)
    rows = [
        [
            str(item.id),
            item.input,
            item.expected_output,
            item.actual_output,
            item.context,
            item.metadata,
            item.id in missing_output_item_ids,
            # Single-run experiments keep their pre-repeat fingerprint.
            *([repeat] if repeat else []),
        ]
        for item, repeat in sorted(
            zip(items, reps, strict=True), key=lambda pair: (str(pair[0].id), pair[1])
        )
    ]
    payload = json.dumps(rows, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


async def load_scoring_inputs(
    experiment: Experiment,
    datasets: DatasetRepository,
    outputs: ExperimentItemOutputRepository,
) -> ScoringInputs:
    items = await datasets.list_items(experiment.dataset_id)
    output_rows = await outputs.list_by_experiment(experiment.id)
    by_item: dict[uuid.UUID, list[ExperimentItemOutput]] = {}
    for row in output_rows:
        by_item.setdefault(row.dataset_item_id, []).append(row)
    # Once an experiment records its own outputs, dataset-level actual_output/context
    # belong to some other run: never fall back to them. Items without an output are
    # failures of this experiment. Experiments with no outputs at all keep the legacy
    # inline-dataset behavior (e.g. datasets built from traces).
    has_outputs = bool(output_rows)
    merged: list[DatasetItem] = []
    repeats: list[int] = []
    for item in items:
        rows: list[ExperimentItemOutput | None] = [
            *sorted(by_item.get(item.id, []), key=lambda o: o.repeat)
        ]
        for output in rows or [None]:
            merged.append(merge_dataset_item(item, output, fallback_to_item=not has_outputs))
            repeats.append(output.repeat if output is not None else 0)
    missing = (
        frozenset(item.id for item in items if item.id not in by_item)
        if has_outputs
        else frozenset()
    )
    return ScoringInputs(
        items=merged,
        missing_output_item_ids=missing,
        fingerprint=fingerprint_items(merged, missing, repeats),
        repeats=repeats,
    )


class CurrentScoringFingerprint:
    """Resolves the fingerprint an experiment would be scored with right now."""

    def __init__(
        self, datasets: DatasetRepository, outputs: ExperimentItemOutputRepository
    ) -> None:
        self._datasets = datasets
        self._outputs = outputs

    async def execute(self, experiment: Experiment) -> str:
        inputs = await load_scoring_inputs(experiment, self._datasets, self._outputs)
        return inputs.fingerprint


async def current_fingerprint(
    resolver: CurrentScoringFingerprint | None, experiment: Experiment
) -> str | None:
    """None (no staleness filter) when no resolver is wired, e.g. in unit tests."""
    if resolver is None:
        return None
    return await resolver.execute(experiment)
