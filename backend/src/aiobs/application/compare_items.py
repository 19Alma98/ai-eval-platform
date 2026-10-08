from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from aiobs.application.experiment_outputs import resolve_item_fields
from aiobs.application.experiments import ExperimentNotFoundError
from aiobs.domain.evaluation import EvaluationResultRecord
from aiobs.domain.repositories import (
    DatasetRepository,
    EvaluationRunRepository,
    ExperimentItemOutputRepository,
    ExperimentRepository,
)
from aiobs.regression.aggregate import MetricStatus, classify_delta, select_latest_runs


class DatasetMismatchError(Exception):
    def __init__(
        self,
        experiment_id: uuid.UUID,
        baseline_id: uuid.UUID,
    ) -> None:
        self.experiment_id = experiment_id
        self.baseline_id = baseline_id
        super().__init__(f"Experiments {experiment_id} and {baseline_id} use different datasets")


class AmbiguousEvaluatorError(Exception):
    def __init__(self) -> None:
        super().__init__("Multiple evaluators have runs; specify evaluator_id query parameter")


@dataclass(frozen=True, slots=True)
class ItemSide:
    actual_output: Any | None
    context: Any | None
    score: float | None
    label: str | None
    explanation: str | None
    run_id: uuid.UUID | None


@dataclass(frozen=True, slots=True)
class ItemComparisonRow:
    dataset_item_id: uuid.UUID
    input: Any
    expected_output: Any | None
    baseline: ItemSide
    candidate: ItemSide
    delta: float | None
    status: MetricStatus


@dataclass(frozen=True, slots=True)
class ItemComparisonResult:
    experiment_id: uuid.UUID
    baseline_experiment_id: uuid.UUID
    evaluator_id: uuid.UUID
    items: list[ItemComparisonRow]


def _resolve_evaluator_id(
    *,
    evaluator_id: uuid.UUID | None,
    candidate_latest: dict[uuid.UUID, Any],
    baseline_latest: dict[uuid.UUID, Any],
) -> uuid.UUID:
    if evaluator_id is not None:
        return evaluator_id

    shared = set(candidate_latest) & set(baseline_latest)
    if len(shared) == 1:
        return next(iter(shared))

    if len(candidate_latest) == 1 and len(baseline_latest) == 1:
        cand_eval = next(iter(candidate_latest))
        base_eval = next(iter(baseline_latest))
        if cand_eval == base_eval:
            return cand_eval

    raise AmbiguousEvaluatorError()


def _result_by_item(
    results: list[EvaluationResultRecord],
) -> dict[uuid.UUID, EvaluationResultRecord]:
    return {r.dataset_item_id: r for r in results}


def _build_side(
    *,
    actual_output: Any | None,
    context: Any | None,
    result: EvaluationResultRecord | None,
    run_id: uuid.UUID | None,
) -> ItemSide:
    if result is None:
        return ItemSide(
            actual_output=actual_output,
            context=context,
            score=None,
            label=None,
            explanation=None,
            run_id=run_id,
        )
    return ItemSide(
        actual_output=actual_output,
        context=context,
        score=result.score,
        label=result.label,
        explanation=result.explanation,
        run_id=run_id,
    )


class CompareExperimentItems:
    def __init__(
        self,
        experiments: ExperimentRepository,
        datasets: DatasetRepository,
        runs: EvaluationRunRepository,
        outputs: ExperimentItemOutputRepository,
    ) -> None:
        self._experiments = experiments
        self._datasets = datasets
        self._runs = runs
        self._outputs = outputs

    async def execute(
        self,
        experiment_id: uuid.UUID,
        baseline_id: uuid.UUID,
        *,
        evaluator_id: uuid.UUID | None = None,
        regressions_only: bool = False,
    ) -> ItemComparisonResult:
        experiment = await self._experiments.get_by_id(experiment_id)
        if experiment is None:
            raise ExperimentNotFoundError(experiment_id)
        baseline = await self._experiments.get_by_id(baseline_id)
        if baseline is None:
            raise ExperimentNotFoundError(baseline_id)

        if experiment.dataset_id != baseline.dataset_id:
            raise DatasetMismatchError(experiment_id, baseline_id)

        candidate_latest = select_latest_runs(
            await self._runs.list_runs_by_experiment(experiment_id)
        )
        baseline_latest = select_latest_runs(await self._runs.list_runs_by_experiment(baseline_id))
        selected_evaluator = _resolve_evaluator_id(
            evaluator_id=evaluator_id,
            candidate_latest=candidate_latest,
            baseline_latest=baseline_latest,
        )

        cand_run = candidate_latest.get(selected_evaluator)
        base_run = baseline_latest.get(selected_evaluator)
        cand_results = _result_by_item(
            await self._runs.list_results(cand_run.id) if cand_run else []
        )
        base_results = _result_by_item(
            await self._runs.list_results(base_run.id) if base_run else []
        )

        cand_outputs = {
            o.dataset_item_id: o for o in await self._outputs.list_by_experiment(experiment_id)
        }
        base_outputs = {
            o.dataset_item_id: o for o in await self._outputs.list_by_experiment(baseline_id)
        }

        dataset_items = await self._datasets.list_items(experiment.dataset_id)
        rows: list[ItemComparisonRow] = []
        for item in sorted(dataset_items, key=lambda i: str(i.id)):
            cand_actual, cand_context = resolve_item_fields(
                item, cand_outputs.get(item.id), fallback_to_item=not cand_outputs
            )
            base_actual, base_context = resolve_item_fields(
                item, base_outputs.get(item.id), fallback_to_item=not base_outputs
            )
            cand_result = cand_results.get(item.id)
            base_result = base_results.get(item.id)
            cand_side = _build_side(
                actual_output=cand_actual,
                context=cand_context,
                result=cand_result,
                run_id=cand_run.id if cand_run else None,
            )
            base_side = _build_side(
                actual_output=base_actual,
                context=base_context,
                result=base_result,
                run_id=base_run.id if base_run else None,
            )
            delta, status = classify_delta(cand_side.score, base_side.score)
            rows.append(
                ItemComparisonRow(
                    dataset_item_id=item.id,
                    input=item.input,
                    expected_output=item.expected_output,
                    baseline=base_side,
                    candidate=cand_side,
                    delta=delta,
                    status=status,
                )
            )

        if regressions_only:
            rows = [row for row in rows if row.status == "regression"]

        return ItemComparisonResult(
            experiment_id=experiment_id,
            baseline_experiment_id=baseline_id,
            evaluator_id=selected_evaluator,
            items=rows,
        )
