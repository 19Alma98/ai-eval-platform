from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from aiobs.application.experiments import ExperimentNotFoundError
from aiobs.domain.evaluation import EvaluationRun
from aiobs.domain.repositories import (
    EvaluationRunRepository,
    EvaluatorRepository,
    ExperimentRepository,
)
from aiobs.regression.aggregate import (
    Aggregates,
    MetricComparison,
    aggregate_results,
    compare_evaluator_metrics,
    runs_config_mismatch,
    select_runs,
)


class InvalidCompareSelectionError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class EvaluatorSummary:
    evaluator_id: uuid.UUID
    evaluator_name: str | None
    run_id: uuid.UUID
    status: str
    aggregates: Aggregates


@dataclass(frozen=True, slots=True)
class ExperimentSummary:
    experiment_id: uuid.UUID
    evaluators: list[EvaluatorSummary]


@dataclass(frozen=True, slots=True)
class CompareRunRef:
    evaluator_id: uuid.UUID
    run_id: uuid.UUID
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ExperimentComparison:
    experiment_id: uuid.UUID
    baseline_experiment_id: uuid.UUID
    metrics: list[MetricComparison]
    regressions: list[MetricComparison]
    improved: list[MetricComparison]
    unchanged: list[MetricComparison]
    config_mismatches: list[MetricComparison]
    insufficient_n: list[MetricComparison]
    candidate_runs: list[CompareRunRef] = field(default_factory=list)
    baseline_runs: list[CompareRunRef] = field(default_factory=list)


def _metadata_evaluator_name(run: EvaluationRun) -> str | None:
    name = run.metadata.get("evaluator_name")
    if name is None:
        return None
    cleaned = str(name).strip()
    return cleaned or None


async def _resolve_evaluator_names(
    evaluators: EvaluatorRepository,
    runs: list[EvaluationRun],
) -> dict[uuid.UUID, str | None]:
    ids = list({run.evaluator_id for run in runs})
    entities = await evaluators.get_by_ids(ids) if ids else []
    by_id = {entity.id: entity.name for entity in entities}
    resolved: dict[uuid.UUID, str | None] = {}
    for run in runs:
        resolved[run.evaluator_id] = _metadata_evaluator_name(run) or by_id.get(run.evaluator_id)
    return resolved


class SummarizeExperiment:
    def __init__(
        self,
        experiments: ExperimentRepository,
        runs: EvaluationRunRepository,
        evaluators: EvaluatorRepository,
    ) -> None:
        self._experiments = experiments
        self._runs = runs
        self._evaluators = evaluators

    async def execute(
        self,
        experiment_id: uuid.UUID,
        *,
        run_ids: list[uuid.UUID] | None = None,
        evaluator_ids: list[uuid.UUID] | None = None,
    ) -> ExperimentSummary:
        experiment = await self._experiments.get_by_id(experiment_id)
        if experiment is None:
            raise ExperimentNotFoundError(experiment_id)

        all_runs = await self._runs.list_runs_by_experiment(experiment_id)
        try:
            selected = select_runs(
                all_runs,
                run_ids=run_ids,
                evaluator_ids=evaluator_ids,
            )
        except ValueError as exc:
            raise InvalidCompareSelectionError(str(exc)) from exc

        if not selected:
            return ExperimentSummary(experiment_id=experiment_id, evaluators=[])

        names = await _resolve_evaluator_names(self._evaluators, selected)
        summaries: list[EvaluatorSummary] = []
        for run in sorted(selected, key=lambda r: str(r.evaluator_id)):
            results = await self._runs.list_results(run.id)
            summaries.append(
                EvaluatorSummary(
                    evaluator_id=run.evaluator_id,
                    evaluator_name=names.get(run.evaluator_id),
                    run_id=run.id,
                    status=run.status,
                    aggregates=aggregate_results(results),
                )
            )
        return ExperimentSummary(experiment_id=experiment_id, evaluators=summaries)


class CompareExperiments:
    def __init__(
        self,
        experiments: ExperimentRepository,
        runs: EvaluationRunRepository,
        evaluators: EvaluatorRepository,
    ) -> None:
        self._experiments = experiments
        self._runs = runs
        self._evaluators = evaluators

    async def execute(
        self,
        experiment_id: uuid.UUID,
        baseline_id: uuid.UUID,
        *,
        evaluator_ids: list[uuid.UUID] | None = None,
        candidate_run_ids: list[uuid.UUID] | None = None,
        baseline_run_ids: list[uuid.UUID] | None = None,
    ) -> ExperimentComparison:
        experiment = await self._experiments.get_by_id(experiment_id)
        if experiment is None:
            raise ExperimentNotFoundError(experiment_id)
        baseline = await self._experiments.get_by_id(baseline_id)
        if baseline is None:
            raise ExperimentNotFoundError(baseline_id)

        if experiment.dataset_id != baseline.dataset_id:
            raise InvalidCompareSelectionError(
                "Runs must share the same dataset (test set version)"
            )

        candidate_runs = await self._runs.list_runs_by_experiment(experiment_id)
        baseline_runs = await self._runs.list_runs_by_experiment(baseline_id)

        try:
            selected_candidate = select_runs(
                candidate_runs,
                run_ids=candidate_run_ids,
                evaluator_ids=evaluator_ids,
            )
            selected_baseline = select_runs(
                baseline_runs,
                run_ids=baseline_run_ids,
                evaluator_ids=evaluator_ids,
            )
        except ValueError as exc:
            raise InvalidCompareSelectionError(str(exc)) from exc

        if not selected_candidate:
            raise InvalidCompareSelectionError(
                f"No evaluation runs selected for experiment {experiment_id}"
            )
        if not selected_baseline:
            raise InvalidCompareSelectionError(
                f"No evaluation runs selected for experiment {baseline_id}"
            )

        candidate_by_eval = {run.evaluator_id: run for run in selected_candidate}
        baseline_by_eval = {run.evaluator_id: run for run in selected_baseline}
        shared = sorted(
            set(candidate_by_eval) & set(baseline_by_eval),
            key=str,
        )
        if not shared:
            raise InvalidCompareSelectionError(
                "No overlapping evaluators between candidate and baseline selections"
            )

        names = await _resolve_evaluator_names(
            self._evaluators,
            [*selected_candidate, *selected_baseline],
        )
        metrics: list[MetricComparison] = []
        candidate_run_refs: list[CompareRunRef] = []
        baseline_run_refs: list[CompareRunRef] = []
        for evaluator_id in shared:
            cand_run = candidate_by_eval[evaluator_id]
            base_run = baseline_by_eval[evaluator_id]
            cand_agg = aggregate_results(await self._runs.list_results(cand_run.id))
            base_agg = aggregate_results(await self._runs.list_results(base_run.id))
            name = names.get(evaluator_id)
            metrics.extend(
                compare_evaluator_metrics(
                    evaluator_id=evaluator_id,
                    evaluator_name=name,
                    candidate=cand_agg,
                    baseline=base_agg,
                    config_mismatch=runs_config_mismatch(cand_run, base_run),
                )
            )
            candidate_run_refs.append(
                CompareRunRef(
                    evaluator_id=evaluator_id,
                    run_id=cand_run.id,
                    metadata=dict(cand_run.metadata),
                )
            )
            baseline_run_refs.append(
                CompareRunRef(
                    evaluator_id=evaluator_id,
                    run_id=base_run.id,
                    metadata=dict(base_run.metadata),
                )
            )

        regressions = [m for m in metrics if m.status == "regression"]
        improved = [m for m in metrics if m.status == "improved"]
        unchanged = [m for m in metrics if m.status == "unchanged"]
        config_mismatches = [m for m in metrics if m.status == "config_mismatch"]
        insufficient_n = [m for m in metrics if m.status == "insufficient_n"]
        return ExperimentComparison(
            experiment_id=experiment_id,
            baseline_experiment_id=baseline_id,
            metrics=metrics,
            regressions=regressions,
            improved=improved,
            unchanged=unchanged,
            config_mismatches=config_mismatches,
            insufficient_n=insufficient_n,
            candidate_runs=candidate_run_refs,
            baseline_runs=baseline_run_refs,
        )
