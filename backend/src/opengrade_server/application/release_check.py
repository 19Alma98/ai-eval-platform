from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from typing import Any

from opengrade_server.application.compare import (
    CompareExperiments,
    InvalidCompareSelectionError,
    load_item_groups,
)
from opengrade_server.application.experiments import ExperimentNotFoundError
from opengrade_server.application.projects import ProjectNotFoundError
from opengrade_server.application.scoring_inputs import (
    CurrentScoringFingerprint,
    current_fingerprint,
)
from opengrade_server.domain.evaluation import EvaluationRun
from opengrade_server.domain.experiment import Experiment
from opengrade_server.domain.repositories import (
    DatasetRepository,
    EvaluationRunRepository,
    ExperimentMetricRepository,
    ExperimentRepository,
    ProjectRepository,
)
from opengrade_server.regression.aggregate import aggregate_results, select_runs
from opengrade_server.regression.groups import results_in
from opengrade_server.regression.policy import (
    EvaluatorMetricInput,
    GroupInput,
    InvalidPolicyError,
    PolicyCheck,
    PolicyEvaluation,
    RegressionDeltaInput,
    evaluate_policy,
    parse_release_policy,
    strip_meta_keys,
)


class MissingBaselineError(Exception):
    def __init__(self) -> None:
        super().__init__(
            "baseline_experiment_id is required when policy includes regression, "
            "groups.max_delta or a relative bound (max_increase_pct, max_increase, …)"
        )


@dataclass(frozen=True, slots=True)
class ReleaseCheckResult:
    status: str
    experiment_id: uuid.UUID
    baseline_experiment_id: uuid.UUID | None
    checks: PolicyEvaluation


@dataclass(frozen=True, slots=True)
class ReleaseCheckCommand:
    project_id: uuid.UUID
    experiment_id: uuid.UUID
    policy: dict[str, Any]
    baseline_experiment_id: uuid.UUID | None = None


def _evaluator_name(run: EvaluationRun) -> str | None:
    name = run.metadata.get("evaluator_name")
    return str(name) if name is not None else None


class ReleaseCheck:
    def __init__(
        self,
        projects: ProjectRepository,
        experiments: ExperimentRepository,
        runs: EvaluationRunRepository,
        compare: CompareExperiments,
        fingerprints: CurrentScoringFingerprint | None = None,
        metrics: ExperimentMetricRepository | None = None,
        datasets: DatasetRepository | None = None,
    ) -> None:
        self._projects = projects
        self._experiments = experiments
        self._runs = runs
        self._compare = compare
        self._fingerprints = fingerprints
        self._metrics = metrics
        self._datasets = datasets

    async def execute(self, command: ReleaseCheckCommand) -> ReleaseCheckResult:
        project = await self._projects.get_by_id(command.project_id)
        if project is None:
            raise ProjectNotFoundError(command.project_id)

        experiment = await self._experiments.get_by_id(command.experiment_id)
        if experiment is None or experiment.project_id != command.project_id:
            raise ExperimentNotFoundError(command.experiment_id)

        try:
            policy = parse_release_policy(strip_meta_keys(command.policy))
        except InvalidPolicyError:
            raise

        candidate = await self._metric_inputs(experiment)

        baseline_id: uuid.UUID | None = None
        group_deltas: dict[str, dict[str, float | None]] = {}
        group_statuses: dict[str, dict[str, str]] = {}
        regression_deltas: list[RegressionDeltaInput] = []
        saw_insufficient_n = False
        allow_insufficient_n = (
            policy.regression is not None and policy.regression.allow_insufficient_n
        )
        need_compare = policy.regression is not None or (
            policy.groups is not None and policy.groups.max_delta is not None
        )
        baseline_inputs: list[EvaluatorMetricInput] = []
        baseline_experiment_metrics: dict[str, float] = {}
        if policy.needs_baseline():
            baseline_id = command.baseline_experiment_id or experiment.baseline_experiment_id
            if baseline_id is None:
                raise MissingBaselineError()
            baseline = await self._experiments.get_by_id(baseline_id)
            if baseline is None or baseline.project_id != command.project_id:
                raise ExperimentNotFoundError(baseline_id)
            relative_eval = (
                policy.latency is not None and policy.latency.max_increase_pct is not None
            ) or (policy.cost is not None and policy.cost.max_increase_pct is not None)
            if relative_eval:
                baseline_inputs = await self._metric_inputs(baseline)
            if self._metrics is not None and any(
                rule.is_relative for rule in policy.experiment_metrics
            ):
                baseline_experiment_metrics = await self._metrics.get(baseline_id)
        if need_compare:
            assert baseline_id is not None
            comparison = await self._compare.execute(
                command.experiment_id,
                baseline_id,
                group_by=policy.groups.by if policy.groups is not None else None,
            )
            group_deltas = {
                group.value: {
                    m.evaluator_name or str(m.evaluator_id): m.delta
                    for m in group.metrics
                    if m.metric == "mean_score"
                }
                for group in comparison.groups
            }
            group_statuses = {
                group.value: {
                    m.evaluator_name or str(m.evaluator_id): m.status
                    for m in group.metrics
                    if m.metric == "mean_score"
                }
                for group in comparison.groups
            }
            if policy.regression is not None:
                for metric in comparison.metrics:
                    if metric.metric != "mean_score":
                        continue
                    name = metric.evaluator_name or str(metric.evaluator_id)
                    if metric.status == "insufficient_n":
                        saw_insufficient_n = True
                        if allow_insufficient_n:
                            continue
                        regression_deltas.append(
                            RegressionDeltaInput(
                                evaluator_name=name,
                                mean_score_delta=metric.delta,
                                insufficient_n=True,
                                compare_status=metric.status,
                            )
                        )
                        continue
                    regression_deltas.append(
                        RegressionDeltaInput(
                            evaluator_name=name,
                            mean_score_delta=metric.delta,
                            compare_status=metric.status,
                        )
                    )

        policy_for_eval = policy
        if (
            policy.regression is not None
            and allow_insufficient_n
            and not regression_deltas
            and saw_insufficient_n
        ):
            policy_for_eval = replace(policy, regression=None)

        experiment_metrics: dict[str, float] = {}
        if policy.experiment_metrics and self._metrics is not None:
            experiment_metrics = await self._metrics.get(command.experiment_id)
        groups: list[GroupInput] = []
        if policy.groups is not None:
            try:
                by_value = await load_item_groups(
                    self._datasets, experiment.dataset_id, policy.groups.by
                )
            except InvalidCompareSelectionError as exc:
                raise InvalidPolicyError(f"policy.groups: {exc}") from exc
            groups = [
                GroupInput(
                    value=value,
                    n_items=len(item_ids),
                    mean_scores={
                        metric.evaluator_name: aggregate_results(
                            results_in(metric.results, item_ids)
                        ).mean_score
                        for metric in candidate
                    },
                    deltas=group_deltas.get(value, {}),
                    statuses=group_statuses.get(value, {}),
                )
                for value, item_ids in by_value.items()
            ]
        evaluation = evaluate_policy(
            policy_for_eval,
            candidate=candidate,
            regression_deltas=regression_deltas,
            experiment_metrics=experiment_metrics,
            groups=groups,
            baseline=baseline_inputs,
            baseline_experiment_metrics=baseline_experiment_metrics,
        )
        if (
            policy.regression is not None
            and allow_insufficient_n
            and not regression_deltas
            and saw_insufficient_n
            and not evaluation.checks
        ):
            evaluation = PolicyEvaluation(
                status="passed",
                checks=(
                    PolicyCheck(
                        metric="regression.max_delta",
                        actual=None,
                        threshold=policy.regression.max_delta,
                        status="passed",
                    ),
                ),
            )
        return ReleaseCheckResult(
            status=evaluation.status,
            experiment_id=command.experiment_id,
            baseline_experiment_id=baseline_id,
            checks=evaluation,
        )

    async def _metric_inputs(self, experiment: Experiment) -> list[EvaluatorMetricInput]:
        """Per-evaluator scores of the experiment's current (non-stale) runs."""
        all_runs = await self._runs.list_runs_by_experiment(experiment.id)
        try:
            # Stale runs (outputs or test set changed after scoring) must not gate a
            # release: their metrics show up as unavailable until re-scored.
            selected = select_runs(
                all_runs,
                current_fingerprint=await current_fingerprint(self._fingerprints, experiment),
                run_ids_with_results=await self._runs.list_run_ids_with_results(experiment.id),
            )
        except ValueError as exc:
            raise InvalidCompareSelectionError(str(exc)) from exc

        inputs: list[EvaluatorMetricInput] = []
        for run in selected:
            name = _evaluator_name(run)
            if name is None:
                continue
            results = await self._runs.list_results(run.id)
            inputs.append(
                EvaluatorMetricInput(
                    evaluator_id=run.evaluator_id,
                    evaluator_name=name,
                    mean_score=aggregate_results(results).mean_score,
                    results=tuple(results),
                )
            )
        return inputs
