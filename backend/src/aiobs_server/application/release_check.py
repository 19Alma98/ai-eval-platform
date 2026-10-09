from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from typing import Any

from aiobs_server.application.compare import (
    CompareExperiments,
    InvalidCompareSelectionError,
)
from aiobs_server.application.experiments import ExperimentNotFoundError
from aiobs_server.application.projects import ProjectNotFoundError
from aiobs_server.domain.evaluation import EvaluationRun
from aiobs_server.domain.repositories import (
    EvaluationRunRepository,
    ExperimentRepository,
    ProjectRepository,
)
from aiobs_server.regression.aggregate import aggregate_results, select_runs
from aiobs_server.regression.policy import (
    EvaluatorMetricInput,
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
        super().__init__("baseline_experiment_id is required when policy includes regression")


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
    ) -> None:
        self._projects = projects
        self._experiments = experiments
        self._runs = runs
        self._compare = compare

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

        all_runs = await self._runs.list_runs_by_experiment(command.experiment_id)
        try:
            selected = select_runs(all_runs)
        except ValueError as exc:
            raise InvalidCompareSelectionError(str(exc)) from exc

        candidate: list[EvaluatorMetricInput] = []
        for run in selected:
            name = _evaluator_name(run)
            if name is None:
                continue
            results = await self._runs.list_results(run.id)
            aggregates = aggregate_results(results)
            candidate.append(
                EvaluatorMetricInput(
                    evaluator_id=run.evaluator_id,
                    evaluator_name=name,
                    mean_score=aggregates.mean_score,
                    results=tuple(results),
                )
            )

        baseline_id: uuid.UUID | None = None
        regression_deltas: list[RegressionDeltaInput] = []
        saw_insufficient_n = False
        if policy.regression is not None:
            baseline_id = command.baseline_experiment_id or experiment.baseline_experiment_id
            if baseline_id is None:
                raise MissingBaselineError()
            baseline = await self._experiments.get_by_id(baseline_id)
            if baseline is None or baseline.project_id != command.project_id:
                raise ExperimentNotFoundError(baseline_id)
            comparison = await self._compare.execute(command.experiment_id, baseline_id)
            for metric in comparison.metrics:
                if metric.metric != "mean_score":
                    continue
                if metric.status == "insufficient_n":
                    saw_insufficient_n = True
                    continue
                name = metric.evaluator_name or str(metric.evaluator_id)
                regression_deltas.append(
                    RegressionDeltaInput(
                        evaluator_name=name,
                        mean_score_delta=metric.delta,
                    )
                )

        policy_for_eval = policy
        if policy.regression is not None and not regression_deltas and saw_insufficient_n:
            policy_for_eval = replace(policy, regression=None)

        evaluation = evaluate_policy(
            policy_for_eval,
            candidate=candidate,
            regression_deltas=regression_deltas,
        )
        if (
            policy.regression is not None
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
