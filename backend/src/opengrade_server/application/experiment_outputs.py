from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from opengrade_server.application.experiments import ExperimentNotFoundError
from opengrade_server.domain.dataset import DatasetItem
from opengrade_server.domain.experiment_output import UNSET, ExperimentItemOutput
from opengrade_server.domain.rag_models import metadata_as_mapping, parse_context, parse_metadata
from opengrade_server.domain.repositories import (
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
    repeat: int = 0
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
    output_meta = dict(output.metadata) if output is not None else {}
    metadata = parse_metadata({**output_meta, **metadata_as_mapping(item.metadata)})
    return DatasetItem(
        id=item.id,
        dataset_id=item.dataset_id,
        input=item.input,
        expected_output=item.expected_output,
        actual_output=actual_output,
        context=parse_context(context),
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

            existing = await self._outputs.get(experiment_id, entry.dataset_item_id, entry.repeat)
            if existing is None:
                existing = ExperimentItemOutput.create(
                    experiment_id,
                    entry.dataset_item_id,
                    repeat=entry.repeat,
                )
            patched.append(
                existing.with_patch(
                    actual_output=entry.actual_output,
                    context=entry.context,
                    metadata=entry.metadata,
                )
            )
        return await self._outputs.upsert_many(patched)


_OUTPUT_KEY_LIMIT = 500


class InvalidExperimentOutputKeyError(ValueError):
    """Raised when a list-outputs ``key`` query value is malformed."""


def parse_output_keys(raw: list[str] | None) -> list[tuple[uuid.UUID, int]] | None:
    """Parse ``{dataset_item_id}:{repeat}`` query values; ``None`` means no filter."""
    if raw is None:
        return None
    if len(raw) > _OUTPUT_KEY_LIMIT:
        raise InvalidExperimentOutputKeyError(
            f"at most {_OUTPUT_KEY_LIMIT} key filters are allowed per request"
        )
    keys: list[tuple[uuid.UUID, int]] = []
    for value in raw:
        item_id_text, sep, repeat_text = value.partition(":")
        if not sep or not item_id_text or not repeat_text:
            raise InvalidExperimentOutputKeyError(
                f"invalid output key {value!r}; expected '{{dataset_item_id}}:{{repeat}}'"
            )
        try:
            item_id = uuid.UUID(item_id_text)
            repeat = int(repeat_text)
        except ValueError as exc:
            raise InvalidExperimentOutputKeyError(
                f"invalid output key {value!r}; expected '{{dataset_item_id}}:{{repeat}}'"
            ) from exc
        if repeat < 0:
            raise InvalidExperimentOutputKeyError(
                f"invalid output key {value!r}; repeat must be >= 0"
            )
        keys.append((item_id, repeat))
    return keys


class ListExperimentOutputs:
    def __init__(
        self,
        experiments: ExperimentRepository,
        outputs: ExperimentItemOutputRepository,
    ) -> None:
        self._experiments = experiments
        self._outputs = outputs

    async def execute(
        self,
        experiment_id: uuid.UUID,
        *,
        keys: list[tuple[uuid.UUID, int]] | None = None,
    ) -> list[ExperimentItemOutput]:
        experiment = await self._experiments.get_by_id(experiment_id)
        if experiment is None:
            raise ExperimentNotFoundError(experiment_id)
        return await self._outputs.list_by_experiment(experiment_id, keys=keys)
