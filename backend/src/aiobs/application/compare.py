from __future__ import annotations

import uuid
from dataclasses import dataclass

from aiobs.application.experiments import ExperimentNotFoundError
from aiobs.domain.evaluation import EvaluationRun
from aiobs.domain.repositories import EvaluationRunRepository, ExperimentRepository
from aiobs.regression.aggregate import (
    Aggregates,
    MetricComparison,
    aggregate_results,
    compare_evaluator_metrics,
    select_runs,
)


class InvalidCompareSelectionError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class EvaluatorSummary:
    evaluator_id: uuid.UUID
    evaluator_name: str | None
    run_id: uuid.UUID
    aggregates: Aggregates


@dataclass(frozen=True, slots=True)
class ExperimentSummary:
    experiment_id: uuid.UUID
    evaluators: list[EvaluatorSummary]


@dataclass(frozen=True, slots=True)
class ExperimentComparison:
    experiment_id: uuid.UUID
    baseline_experiment_id: uuid.UUID
    metrics: list[MetricComparison]
    regressions: list[MetricComparison]
    improved: list[MetricComparison]
    unchanged: list[MetricComparison]


def _evaluator_name(run: EvaluationRun) -> str | None:
    name = run.metadata.get("evaluator_name")
    return str(name) if name is not None else None


class SummarizeExperiment:
    def __init__(
        self,
        experiments: ExperimentRepository,
        runs: EvaluationRunRepository,
    ) -> None:
        self._experiments = experiments
        self._runs = runs

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

        summaries: list[EvaluatorSummary] = []
        for run in sorted(selected, key=lambda r: str(r.evaluator_id)):
            results = await self._runs.list_results(run.id)
            summaries.append(
                EvaluatorSummary(
                    evaluator_id=run.evaluator_id,
                    evaluator_name=_evaluator_name(run),
                    run_id=run.id,
                    aggregates=aggregate_results(results),
                )
            )
        return ExperimentSummary(experiment_id=experiment_id, evaluators=summaries)


class CompareExperiments:
    def __init__(
        self,
        experiments: ExperimentRepository,
        runs: EvaluationRunRepository,
    ) -> None:
        self._experiments = experiments
        self._runs = runs

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

        metrics: list[MetricComparison] = []
        for evaluator_id in shared:
            cand_run = candidate_by_eval[evaluator_id]
            base_run = baseline_by_eval[evaluator_id]
            cand_agg = aggregate_results(await self._runs.list_results(cand_run.id))
            base_agg = aggregate_results(await self._runs.list_results(base_run.id))
            name = _evaluator_name(cand_run) or _evaluator_name(base_run)
            metrics.extend(
                compare_evaluator_metrics(
                    evaluator_id=evaluator_id,
                    evaluator_name=name,
                    candidate=cand_agg,
                    baseline=base_agg,
                )
            )

        regressions = [m for m in metrics if m.status == "regression"]
        improved = [m for m in metrics if m.status == "improved"]
        unchanged = [m for m in metrics if m.status == "unchanged"]
        return ExperimentComparison(
            experiment_id=experiment_id,
            baseline_experiment_id=baseline_id,
            metrics=metrics,
            regressions=regressions,
            improved=improved,
            unchanged=unchanged,
        )
