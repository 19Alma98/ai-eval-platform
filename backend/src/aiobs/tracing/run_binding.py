from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from aiobs.domain.experiment_output import ExperimentItemOutput
from aiobs.domain.repositories import (
    DatasetRepository,
    ExperimentItemOutputRepository,
    ExperimentRepository,
)
from aiobs.domain.trace import Trace
from aiobs.evaluation.trace_context import build_eval_context_from_trace


def _parse_uuid(value: Any) -> uuid.UUID | None:
    if value is None:
        return None
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def _binding_from_attributes(attributes: dict[str, Any]) -> tuple[uuid.UUID, uuid.UUID] | None:
    experiment_id = _parse_uuid(attributes.get("aiobs.experiment_id"))
    dataset_item_id = _parse_uuid(attributes.get("aiobs.dataset_item_id"))
    if experiment_id is None or dataset_item_id is None:
        return None
    return experiment_id, dataset_item_id


def extract_run_binding(trace: Trace) -> tuple[uuid.UUID, uuid.UUID] | None:
    """Read experiment/dataset-item bind attrs from root or CHAIN spans."""
    spans = list(trace.spans)
    roots = [span for span in spans if not span.parent_span_id]
    chains = [span for span in spans if span.kind.upper() == "CHAIN"]
    seen: set[str] = set()
    for span in (*roots, *chains):
        if span.span_id in seen:
            continue
        seen.add(span.span_id)
        binding = _binding_from_attributes(span.attributes or {})
        if binding is not None:
            return binding
    return None


def build_output_from_trace(trace: Trace) -> dict[str, Any]:
    context = build_eval_context_from_trace(trace)
    return {
        "actual_output": trace.output,
        "context": context or None,
        "metadata": {"source_trace_id": trace.trace_id},
    }


@dataclass(frozen=True, slots=True)
class BindOtlpTracesToExperimentOutputs:
    experiments: ExperimentRepository
    datasets: DatasetRepository
    outputs: ExperimentItemOutputRepository

    async def execute(self, traces: list[Trace]) -> None:
        for trace in traces:
            await self._bind_one(trace)

    async def _bind_one(self, trace: Trace) -> None:
        binding = extract_run_binding(trace)
        if binding is None:
            return
        experiment_id, dataset_item_id = binding

        experiment = await self.experiments.get_by_id(experiment_id)
        if experiment is None:
            return

        dataset_item = await self.datasets.get_item(dataset_item_id)
        if dataset_item is None or dataset_item.dataset_id != experiment.dataset_id:
            return

        payload = build_output_from_trace(trace)
        existing = await self.outputs.get(experiment_id, dataset_item_id)
        if existing is None:
            existing = ExperimentItemOutput.create(experiment_id, dataset_item_id)
        patched = existing.with_patch(
            actual_output=payload["actual_output"],
            context=payload["context"],
            metadata=payload["metadata"],
        )
        await self.outputs.upsert_many([patched])
