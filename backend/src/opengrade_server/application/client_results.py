"""Scores computed outside the platform (e.g. an SDK-side Python metric).

Each submitted metric becomes a regular evaluation run on a ``custom`` evaluator of
kind ``client`` named after the metric, so summary, compare, release check and the
UI treat it like any server-side evaluator. The run records the experiment's current
inputs fingerprint, so it goes stale when outputs or the test set change, exactly
like server-scored runs.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from aiobs_server.application.experiments import ExperimentNotFoundError
from aiobs_server.application.scoring_inputs import INPUTS_FINGERPRINT_KEY, load_scoring_inputs
from aiobs_server.domain.evaluation import EvaluationResultRecord, EvaluationRun
from aiobs_server.domain.evaluator import CLIENT_EVALUATOR_KIND, Evaluator
from aiobs_server.domain.repositories import (
    DatasetRepository,
    EvaluationRunRepository,
    EvaluatorRepository,
    ExperimentItemOutputRepository,
    ExperimentRepository,
)
from aiobs_server.evaluation.outcomes import item_verdict
from aiobs_server.evaluation.runner import config_hash, run_status_from_results

CLIENT_EVALUATOR_TYPE = "custom"
_LABELS = frozenset({"PASS", "FAIL", "ERROR", "SKIPPED"})


class ClientResultsValidationError(Exception):
    pass


class ClientMetricNameConflictError(Exception):
    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(
            f"Metric name {name!r} is already used by a server evaluator; rename the client metric"
        )


@dataclass(frozen=True, slots=True)
class ClientResultItem:
    dataset_item_id: uuid.UUID
    score: float | None = None
    label: str | None = None
    explanation: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ClientMetric:
    name: str
    results: list[ClientResultItem]
    threshold: float | None = None
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SubmitClientResultsCommand:
    experiment_id: uuid.UUID
    metrics: list[ClientMetric]


@dataclass(frozen=True, slots=True)
class SubmittedRun:
    run: EvaluationRun
    results: list[EvaluationResultRecord]


def _result_label(item: ClientResultItem, threshold: float | None) -> str:
    label = (item.label or "").strip().upper() or None
    if label is not None and label not in _LABELS:
        raise ClientResultsValidationError(
            f"label must be one of {sorted(_LABELS)}, got {item.label!r}"
        )
    # Same PASS/FAIL rule as server scoring; nothing to judge means not applicable.
    return item_verdict(item.score, label, threshold) or "SKIPPED"


class SubmitClientResults:
    def __init__(
        self,
        experiments: ExperimentRepository,
        datasets: DatasetRepository,
        outputs: ExperimentItemOutputRepository,
        evaluators: EvaluatorRepository,
        runs: EvaluationRunRepository,
    ) -> None:
        self._experiments = experiments
        self._datasets = datasets
        self._outputs = outputs
        self._evaluators = evaluators
        self._runs = runs

    async def execute(self, command: SubmitClientResultsCommand) -> list[SubmittedRun]:
        experiment = await self._experiments.get_by_id(command.experiment_id)
        if experiment is None:
            raise ExperimentNotFoundError(command.experiment_id)
        self._validate_shape(command.metrics)

        inputs = await load_scoring_inputs(experiment, self._datasets, self._outputs)
        item_ids = {item.id for item in inputs.items}
        for metric in command.metrics:
            unknown = [
                r.dataset_item_id for r in metric.results if r.dataset_item_id not in item_ids
            ]
            if unknown:
                raise ClientResultsValidationError(
                    f"metric {metric.name!r}: dataset item {unknown[0]} is not in the "
                    f"experiment's dataset {experiment.dataset_id}"
                )

        # Resolve every evaluator before writing any run, so a name conflict on the
        # last metric does not leave the first ones half-submitted.
        evaluators = [
            await self._evaluator_for(experiment.project_id, metric.name)
            for metric in command.metrics
        ]

        submitted: list[SubmittedRun] = []
        now = datetime.now(UTC)
        for metric, evaluator in zip(command.metrics, evaluators, strict=True):
            run = EvaluationRun.create(experiment.id, evaluator.id, status="PENDING")
            records = [
                EvaluationResultRecord.create(
                    run.id,
                    r.dataset_item_id,
                    score=r.score,
                    label=_result_label(r, metric.threshold),
                    explanation=r.explanation,
                    metadata=r.metadata,
                )
                for r in metric.results
            ]
            metadata: dict[str, Any] = {
                INPUTS_FINGERPRINT_KEY: inputs.fingerprint,
                "evaluator_name": evaluator.name,
                "evaluator_version": evaluator.version,
                "evaluator_kind": CLIENT_EVALUATOR_KIND,
                "source": "client",
                # Clients bump config (e.g. {"version": 2}) when the metric code changes,
                # so compare reports config_mismatch instead of a bogus delta.
                "config_hash": config_hash(metric.config),
                "threshold": metric.threshold,
            }
            if metric.config:
                metadata["config"] = dict(metric.config)
            run = await self._runs.add_run(run)
            run = await self._runs.update_run(
                run.with_status(
                    run_status_from_results(records),
                    started_at=now,
                    finished_at=now,
                    metadata=metadata,
                )
            )
            records = await self._runs.add_results(records)
            submitted.append(SubmittedRun(run=run, results=records))
        return submitted

    @staticmethod
    def _validate_shape(metrics: list[ClientMetric]) -> None:
        if not metrics:
            raise ClientResultsValidationError("metrics must not be empty")
        names = [m.name.strip() for m in metrics]
        if any(not n for n in names):
            raise ClientResultsValidationError("metric name must not be empty")
        if len(set(names)) != len(names):
            raise ClientResultsValidationError(f"duplicate metric names: {names}")
        for metric in metrics:
            # HTTP bodies are already guarded by RejectNonFiniteJsonMiddleware; kept so no
            # caller can store a NaN that would break every later JSON response.
            if metric.threshold is not None and not math.isfinite(metric.threshold):
                raise ClientResultsValidationError(
                    f"metric {metric.name!r}: threshold must be finite"
                )
            if any(r.score is not None and not math.isfinite(r.score) for r in metric.results):
                raise ClientResultsValidationError(f"metric {metric.name!r}: scores must be finite")
            if not metric.results:
                raise ClientResultsValidationError(f"metric {metric.name!r} has no results")
            ids = [r.dataset_item_id for r in metric.results]
            if len(set(ids)) != len(ids):
                raise ClientResultsValidationError(
                    f"metric {metric.name!r} has duplicate dataset_item_id"
                )
            for r in metric.results:
                _result_label(r, metric.threshold)

    async def _evaluator_for(self, project_id: uuid.UUID, name: str) -> Evaluator:
        cleaned = name.strip()
        found = await self._find(project_id, cleaned)
        if found is not None:
            return found
        evaluator = Evaluator.create(
            project_id,
            cleaned,
            CLIENT_EVALUATOR_TYPE,
            {"kind": CLIENT_EVALUATOR_KIND},
        )
        try:
            return await self._evaluators.add(evaluator)
        except Exception as exc:
            if "unique" not in str(exc).lower():
                raise
            # Created concurrently by another submission: use theirs.
            found = await self._find(project_id, cleaned)
            if found is None:
                raise
            return found

    async def _find(self, project_id: uuid.UUID, name: str) -> Evaluator | None:
        same_name = [
            e for e in await self._evaluators.list_by_project(project_id) if e.name == name
        ]
        if any(not e.is_client for e in same_name):
            raise ClientMetricNameConflictError(name)
        if not same_name:
            return None
        return max(same_name, key=lambda e: e.version)
