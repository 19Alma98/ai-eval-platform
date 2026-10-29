from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from opengrade_server.application.experiments import ExperimentNotFoundError
from opengrade_server.application.scoring_inputs import (
    CurrentScoringFingerprint,
    current_fingerprint,
)
from opengrade_server.domain.evaluation import EvaluationResultRecord, EvaluationRun
from opengrade_server.domain.repositories import (
    DatasetRepository,
    EvaluationRunRepository,
    EvaluatorRepository,
    ExperimentMetricRepository,
    ExperimentRepository,
)
from opengrade_server.regression.aggregate import (
    Aggregates,
    MetricComparison,
    aggregate_results,
    compare_evaluator_metrics,
    runs_config_mismatch,
    select_runs,
)
from opengrade_server.regression.groups import InvalidGroupKeyError, item_groups, results_in


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
class GroupSummary:
    value: str
    n_items: int
    evaluators: list[EvaluatorSummary]


@dataclass(frozen=True, slots=True)
class ExperimentSummary:
    experiment_id: uuid.UUID
    evaluators: list[EvaluatorSummary]
    experiment_metrics: dict[str, float] = field(default_factory=dict)
    group_by: str | None = None
    groups: list[GroupSummary] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class CompareRunRef:
    evaluator_id: uuid.UUID
    run_id: uuid.UUID
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ExperimentMetricComparison:
    key: str
    candidate: float | None
    baseline: float | None
    delta: float | None


def compare_experiment_metrics(
    candidate: Mapping[str, float], baseline: Mapping[str, float]
) -> list[ExperimentMetricComparison]:
    """One row per key on either side; no status — whether higher is better is unknown."""
    rows: list[ExperimentMetricComparison] = []
    for key in sorted(set(candidate) | set(baseline)):
        cand = candidate.get(key)
        base = baseline.get(key)
        delta = cand - base if cand is not None and base is not None else None
        rows.append(ExperimentMetricComparison(key, cand, base, delta))
    return rows


@dataclass(frozen=True, slots=True)
class GroupComparison:
    value: str
    n_items: int
    metrics: list[MetricComparison]

    @property
    def regressions(self) -> list[MetricComparison]:
        return [m for m in self.metrics if m.status == "regression"]


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
    experiment_metrics: list[ExperimentMetricComparison] = field(default_factory=list)
    candidate_git: dict[str, Any] | None = None
    baseline_git: dict[str, Any] | None = None
    group_by: str | None = None
    groups: list[GroupComparison] = field(default_factory=list)


def _metadata_evaluator_name(run: EvaluationRun) -> str | None:
    name = run.metadata.get("evaluator_name")
    if name is None:
        return None
    cleaned = str(name).strip()
    return cleaned or None


async def load_item_groups(
    datasets: DatasetRepository | None, dataset_id: uuid.UUID, group_by: str
) -> dict[str, set[uuid.UUID]]:
    if datasets is None:
        raise InvalidCompareSelectionError("group_by is not available here")
    try:
        return item_groups(await datasets.list_items(dataset_id), group_by)
    except InvalidGroupKeyError as exc:
        raise InvalidCompareSelectionError(str(exc)) from exc


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
        fingerprints: CurrentScoringFingerprint | None = None,
        metrics: ExperimentMetricRepository | None = None,
        datasets: DatasetRepository | None = None,
    ) -> None:
        self._experiments = experiments
        self._runs = runs
        self._evaluators = evaluators
        self._fingerprints = fingerprints
        self._metrics = metrics
        self._datasets = datasets

    async def execute(
        self,
        experiment_id: uuid.UUID,
        *,
        run_ids: list[uuid.UUID] | None = None,
        evaluator_ids: list[uuid.UUID] | None = None,
        group_by: str | None = None,
    ) -> ExperimentSummary:
        experiment = await self._experiments.get_by_id(experiment_id)
        if experiment is None:
            raise ExperimentNotFoundError(experiment_id)
        experiment_metrics = (
            await self._metrics.get(experiment_id) if self._metrics is not None else {}
        )

        all_runs = await self._runs.list_runs_by_experiment(experiment_id)
        try:
            selected = select_runs(
                all_runs,
                run_ids=run_ids,
                evaluator_ids=evaluator_ids,
                current_fingerprint=await current_fingerprint(self._fingerprints, experiment),
                run_ids_with_results=await self._runs.list_run_ids_with_results(experiment_id),
            )
        except ValueError as exc:
            raise InvalidCompareSelectionError(str(exc)) from exc

        if not selected:
            return ExperimentSummary(
                experiment_id=experiment_id,
                evaluators=[],
                experiment_metrics=experiment_metrics,
            )

        names = await _resolve_evaluator_names(self._evaluators, selected)
        summaries: list[EvaluatorSummary] = []
        results_by_run: dict[uuid.UUID, list[EvaluationResultRecord]] = {}
        ordered = sorted(selected, key=lambda r: str(r.evaluator_id))
        for run in ordered:
            results = await self._runs.list_results(run.id)
            results_by_run[run.id] = results
            summaries.append(
                EvaluatorSummary(
                    evaluator_id=run.evaluator_id,
                    evaluator_name=names.get(run.evaluator_id),
                    run_id=run.id,
                    status=run.status,
                    aggregates=aggregate_results(results),
                )
            )
        groups: list[GroupSummary] = []
        if group_by is not None:
            for value, item_ids in (
                await load_item_groups(self._datasets, experiment.dataset_id, group_by)
            ).items():
                groups.append(
                    GroupSummary(
                        value=value,
                        n_items=len(item_ids),
                        evaluators=[
                            replace(
                                summary,
                                aggregates=aggregate_results(
                                    results_in(results_by_run[summary.run_id], item_ids)
                                ),
                            )
                            for summary in summaries
                        ],
                    )
                )
        return ExperimentSummary(
            experiment_id=experiment_id,
            evaluators=summaries,
            experiment_metrics=experiment_metrics,
            group_by=group_by,
            groups=groups,
        )


MAX_SUMMARIZED_EXPERIMENTS = 100


class SummarizeExperiments:
    """Summaries for many experiments of a project (the N-way comparison table)."""

    def __init__(self, experiments: ExperimentRepository, summarize: SummarizeExperiment) -> None:
        self._experiments = experiments
        self._summarize = summarize

    async def execute(
        self, project_id: uuid.UUID, *, experiment_ids: list[uuid.UUID] | None = None
    ) -> list[ExperimentSummary]:
        experiments = await self._experiments.list_by_project(project_id)
        if experiment_ids:
            wanted = set(experiment_ids)
            experiments = [e for e in experiments if e.id in wanted]
        out: list[ExperimentSummary] = []
        for experiment in experiments[:MAX_SUMMARIZED_EXPERIMENTS]:
            try:
                out.append(await self._summarize.execute(experiment.id))
            except InvalidCompareSelectionError:
                # Ambiguous runs: show the experiment without scores rather than fail the table.
                out.append(ExperimentSummary(experiment_id=experiment.id, evaluators=[]))
        return out


class CompareExperiments:
    def __init__(
        self,
        experiments: ExperimentRepository,
        runs: EvaluationRunRepository,
        evaluators: EvaluatorRepository,
        fingerprints: CurrentScoringFingerprint | None = None,
        metrics: ExperimentMetricRepository | None = None,
        datasets: DatasetRepository | None = None,
    ) -> None:
        self._experiments = experiments
        self._runs = runs
        self._evaluators = evaluators
        self._fingerprints = fingerprints
        self._metrics = metrics
        self._datasets = datasets

    async def execute(
        self,
        experiment_id: uuid.UUID,
        baseline_id: uuid.UUID,
        *,
        evaluator_ids: list[uuid.UUID] | None = None,
        candidate_run_ids: list[uuid.UUID] | None = None,
        baseline_run_ids: list[uuid.UUID] | None = None,
        group_by: str | None = None,
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
                current_fingerprint=await current_fingerprint(self._fingerprints, experiment),
                run_ids_with_results=await self._runs.list_run_ids_with_results(experiment_id),
            )
            selected_baseline = select_runs(
                baseline_runs,
                run_ids=baseline_run_ids,
                evaluator_ids=evaluator_ids,
                current_fingerprint=await current_fingerprint(self._fingerprints, baseline),
                run_ids_with_results=await self._runs.list_run_ids_with_results(baseline_id),
            )
        except ValueError as exc:
            raise InvalidCompareSelectionError(str(exc)) from exc

        if not selected_candidate:
            raise InvalidCompareSelectionError(
                f"No current evaluation runs for experiment {experiment_id}: "
                "score it, or re-score if its outputs or test set changed"
            )
        if not selected_baseline:
            raise InvalidCompareSelectionError(
                f"No current evaluation runs for experiment {baseline_id}: "
                "score it, or re-score if its outputs or test set changed"
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
        item_groups_by_value = (
            await load_item_groups(self._datasets, experiment.dataset_id, group_by)
            if group_by is not None
            else {}
        )
        group_metrics: dict[str, list[MetricComparison]] = {v: [] for v in item_groups_by_value}
        metrics: list[MetricComparison] = []
        candidate_run_refs: list[CompareRunRef] = []
        baseline_run_refs: list[CompareRunRef] = []
        for evaluator_id in shared:
            cand_run = candidate_by_eval[evaluator_id]
            base_run = baseline_by_eval[evaluator_id]
            cand_results = await self._runs.list_results(cand_run.id)
            base_results = await self._runs.list_results(base_run.id)
            mismatch = runs_config_mismatch(cand_run, base_run)
            for value, item_ids in item_groups_by_value.items():
                cand_group = results_in(cand_results, item_ids)
                base_group = results_in(base_results, item_ids)
                group_metrics[value].extend(
                    compare_evaluator_metrics(
                        evaluator_id=evaluator_id,
                        evaluator_name=names.get(evaluator_id),
                        candidate=aggregate_results(cand_group),
                        baseline=aggregate_results(base_group),
                        candidate_results=cand_group,
                        baseline_results=base_group,
                        candidate_run_id=cand_run.id,
                        baseline_run_id=base_run.id,
                        config_mismatch=mismatch,
                    )
                )
            cand_agg = aggregate_results(cand_results)
            base_agg = aggregate_results(base_results)
            name = names.get(evaluator_id)
            metrics.extend(
                compare_evaluator_metrics(
                    evaluator_id=evaluator_id,
                    evaluator_name=name,
                    candidate=cand_agg,
                    baseline=base_agg,
                    candidate_results=cand_results,
                    baseline_results=base_results,
                    candidate_run_id=cand_run.id,
                    baseline_run_id=base_run.id,
                    config_mismatch=mismatch,
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
        experiment_metrics: list[ExperimentMetricComparison] = []
        if self._metrics is not None:
            experiment_metrics = compare_experiment_metrics(
                await self._metrics.get(experiment_id),
                await self._metrics.get(baseline_id),
            )
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
            experiment_metrics=experiment_metrics,
            candidate_git=experiment.git,
            baseline_git=baseline.git,
            group_by=group_by,
            groups=[
                GroupComparison(value=value, n_items=len(item_ids), metrics=group_metrics[value])
                for value, item_ids in item_groups_by_value.items()
            ],
        )
