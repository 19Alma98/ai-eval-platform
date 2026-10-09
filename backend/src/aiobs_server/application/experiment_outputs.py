from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from aiobs_server.application.experiments import ExperimentNotFoundError
from aiobs_server.domain.dataset import DatasetItem
from aiobs_server.domain.experiment_output import UNSET, ExperimentItemOutput
from aiobs_server.domain.repositories import (
    DatasetRepository,
    ExperimentItemOutputRepository,
    ExperimentRepository,
)


class ExperimentItemNotInDatasetError(Exception):
    def __init__(self, experiment_id: uuid.UUID, dataset_item_id: uuid.UUID) -> None:
        self.experiment_id = experiment_id
        self.dataset_item_id = dataset_item_id
        super().__init__(
            f"Dataset item {dataset_item_id} is not in experiment {experiment_id} dataset"
        )


@dataclass(frozen=True, slots=True)
class UpsertOutputItem:
    dataset_item_id: uuid.UUID
    actual_output: Any = UNSET
    context: Any = UNSET
    metadata: Any = UNSET


def resolve_item_fields(
    item: DatasetItem,
    output: ExperimentItemOutput | None,
    *,
    fallback_to_item: bool = True,
) -> tuple[Any | None, Any | None]:
    """Resolve actual_output/context for an item within one experiment.

    ``fallback_to_item`` must be False when the experiment has recorded outputs:
    dataset-level fields then belong to another run and would leak across experiments.
    """
    if not fallback_to_item:
        if output is None:
            return None, None
        return output.actual_output, output.context
    if output is None:
        return item.actual_output, item.context
    actual = item.actual_output if output.actual_output is None else output.actual_output
    context = item.context if output.context is None else output.context
    return actual, context


def merge_dataset_item(
    item: DatasetItem,
    output: ExperimentItemOutput | None,
    *,
    fallback_to_item: bool = True,
) -> DatasetItem:
    actual_output, context = resolve_item_fields(item, output, fallback_to_item=fallback_to_item)
    # Item metadata holds the gold labels, so it wins over run-level output metadata.
    metadata = {**(output.metadata if output is not None else {}), **item.metadata}
    return DatasetItem(
        id=item.id,
        dataset_id=item.dataset_id,
        input=item.input,
        expected_output=item.expected_output,
        actual_output=actual_output,
        context=context,
        metadata=metadata,
        source_trace_id=item.source_trace_id,
        source_span_id=item.source_span_id,
    )


class UpsertExperimentOutputs:
    def __init__(
        self,
        experiments: ExperimentRepository,
        datasets: DatasetRepository,
        outputs: ExperimentItemOutputRepository,
    ) -> None:
        self._experiments = experiments
        self._datasets = datasets
        self._outputs = outputs

    async def execute(
        self, experiment_id: uuid.UUID, items: list[UpsertOutputItem]
    ) -> list[ExperimentItemOutput]:
        experiment = await self._experiments.get_by_id(experiment_id)
        if experiment is None:
            raise ExperimentNotFoundError(experiment_id)

        patched: list[ExperimentItemOutput] = []
        for entry in items:
            dataset_item = await self._datasets.get_item(entry.dataset_item_id)
            if dataset_item is None or dataset_item.dataset_id != experiment.dataset_id:
                raise ExperimentItemNotInDatasetError(experiment_id, entry.dataset_item_id)

            existing = await self._outputs.get(experiment_id, entry.dataset_item_id)
            if existing is None:
                existing = ExperimentItemOutput.create(
                    experiment_id,
                    entry.dataset_item_id,
                )
            patched.append(
                existing.with_patch(
                    actual_output=entry.actual_output,
                    context=entry.context,
                    metadata=entry.metadata,
                )
            )
        return await self._outputs.upsert_many(patched)


class ListExperimentOutputs:
    def __init__(
        self,
        experiments: ExperimentRepository,
        outputs: ExperimentItemOutputRepository,
    ) -> None:
        self._experiments = experiments
        self._outputs = outputs

    async def execute(self, experiment_id: uuid.UUID) -> list[ExperimentItemOutput]:
        experiment = await self._experiments.get_by_id(experiment_id)
        if experiment is None:
            raise ExperimentNotFoundError(experiment_id)
        return await self._outputs.list_by_experiment(experiment_id)
