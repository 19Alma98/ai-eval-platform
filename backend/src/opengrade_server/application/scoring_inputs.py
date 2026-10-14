from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass

from aiobs_server.application.experiment_outputs import merge_dataset_item
from aiobs_server.domain.dataset import DatasetItem
from aiobs_server.domain.experiment import Experiment
from aiobs_server.domain.repositories import DatasetRepository, ExperimentItemOutputRepository
from aiobs_server.regression.aggregate import INPUTS_FINGERPRINT_KEY

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
    items: list[DatasetItem]
    missing_output_item_ids: frozenset[uuid.UUID]
    fingerprint: str


def fingerprint_items(
    items: list[DatasetItem], missing_output_item_ids: frozenset[uuid.UUID]
) -> str:
    """Hash everything a score depends on: the gold fields and the recorded output.

    Runs keep the fingerprint they were scored with; when the test set or the
    experiment outputs change afterwards, the run no longer matches and is stale.
    """
    rows = [
        [
            str(item.id),
            item.input,
            item.expected_output,
            item.actual_output,
            item.context,
            item.metadata,
            item.id in missing_output_item_ids,
        ]
        for item in sorted(items, key=lambda i: str(i.id))
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
    by_item = {o.dataset_item_id: o for o in output_rows}
    # Once an experiment records its own outputs, dataset-level actual_output/context
    # belong to some other run: never fall back to them. Items without an output are
    # failures of this experiment. Experiments with no outputs at all keep the legacy
    # inline-dataset behavior (e.g. datasets built from traces).
    has_outputs = bool(output_rows)
    merged = [
        merge_dataset_item(item, by_item.get(item.id), fallback_to_item=not has_outputs)
        for item in items
    ]
    missing = (
        frozenset(item.id for item in items if item.id not in by_item)
        if has_outputs
        else frozenset()
    )
    return ScoringInputs(
        items=merged,
        missing_output_item_ids=missing,
        fingerprint=fingerprint_items(merged, missing),
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
