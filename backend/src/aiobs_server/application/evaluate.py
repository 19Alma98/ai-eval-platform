from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from aiobs_server.application.evaluators import EvaluatorNotFoundError
from aiobs_server.application.experiment_outputs import merge_dataset_item
from aiobs_server.application.experiments import ExperimentNotFoundError
from aiobs_server.application.metrics_sets import (
    MetricsSetValidationError,
    ResolveMetricsSetForScore,
)
from aiobs_server.domain.evaluation import EvaluationResultRecord, EvaluationRun
from aiobs_server.domain.experiment import Experiment
from aiobs_server.domain.metrics_set import assert_unique_evaluator_ids
from aiobs_server.domain.repositories import (
    DatasetRepository,
    EvaluationRunRepository,
    EvaluatorRepository,
    ExperimentItemOutputRepository,
    ExperimentRepository,
)
from aiobs_server.evaluation.runner import EvaluationRunner


class EmptyEvaluatorListError(Exception):
    def __init__(self) -> None:
        super().__init__("evaluator_ids must not be empty")


@dataclass(frozen=True, slots=True)
class EvaluateExperimentCommand:
    experiment_id: uuid.UUID
    evaluator_ids: list[uuid.UUID]
    pass_thresholds: dict[uuid.UUID, float | None] | None = None
    config_overrides: dict[uuid.UUID, dict[str, Any]] | None = None


@dataclass(frozen=True, slots=True)
class EvaluateExperimentResult:
    experiment: Experiment
    runs: list[EvaluationRun]
    results_by_run: dict[uuid.UUID, list[EvaluationResultRecord]]


class EvaluateExperiment:
    def __init__(
        self,
        experiments: ExperimentRepository,
        datasets: DatasetRepository,
        evaluators: EvaluatorRepository,
        runs: EvaluationRunRepository,
        runner: EvaluationRunner,
        outputs: ExperimentItemOutputRepository,
    ) -> None:
        self._experiments = experiments
        self._datasets = datasets
        self._evaluators = evaluators
        self._runs = runs
        self._runner = runner
        self._outputs = outputs

    async def execute(self, command: EvaluateExperimentCommand) -> EvaluateExperimentResult:
        if not command.evaluator_ids:
            raise EmptyEvaluatorListError()

        experiment = await self._experiments.get_by_id(command.experiment_id)
        if experiment is None:
            raise ExperimentNotFoundError(command.experiment_id)

        items = await self._datasets.list_items(experiment.dataset_id)
        output_rows = await self._outputs.list_by_experiment(experiment.id)
        by_item = {o.dataset_item_id: o for o in output_rows}
        # Once an experiment records its own outputs, dataset-level actual_output/context
        # belong to some other run: never fall back to them. Items without an output are
        # failures of this experiment. Experiments with no outputs at all keep the legacy
        # inline-dataset behavior (e.g. datasets built from traces).
        has_outputs = bool(output_rows)
        merged_items = [
            merge_dataset_item(item, by_item.get(item.id), fallback_to_item=not has_outputs)
            for item in items
        ]
        missing_output_item_ids = (
            frozenset(item.id for item in items if item.id not in by_item)
            if has_outputs
            else frozenset()
        )
        evaluator_entities = await self._evaluators.get_by_ids(command.evaluator_ids)
        by_id = {e.id: e for e in evaluator_entities}
        missing = [eid for eid in command.evaluator_ids if eid not in by_id]
        if missing:
            raise EvaluatorNotFoundError(missing[0])
        for entity in evaluator_entities:
            if entity.project_id != experiment.project_id:
                raise EvaluatorNotFoundError(entity.id)

        experiment = Experiment(
            id=experiment.id,
            project_id=experiment.project_id,
            name=experiment.name,
            dataset_id=experiment.dataset_id,
            model_config=dict(experiment.model_config),
            version=experiment.version,
            baseline_experiment_id=experiment.baseline_experiment_id,
            status="running",
            created_at=experiment.created_at,
            app_config_id=experiment.app_config_id,
            metrics_set_id=experiment.metrics_set_id,
        )
        experiment = await self._experiments.update(experiment)

        finished_runs: list[EvaluationRun] = []
        results_by_run: dict[uuid.UUID, list[EvaluationResultRecord]] = {}

        for evaluator_id in command.evaluator_ids:
            entity = by_id[evaluator_id]
            run = EvaluationRun.create(experiment.id, entity.id, status="PENDING")
            run = await self._runs.add_run(run)
            pass_threshold = (
                None
                if command.pass_thresholds is None
                else command.pass_thresholds.get(evaluator_id)
            )
            config_override = (
                None
                if command.config_overrides is None
                else command.config_overrides.get(evaluator_id)
            )
            run, results = await self._runner.run_evaluator(
                run=run,
                evaluator_entity=entity,
                items=merged_items,
                pass_threshold=pass_threshold,
                config_override=config_override,
                missing_output_item_ids=missing_output_item_ids,
            )
            run = await self._runs.update_run(run)
            if results:
                results = await self._runs.add_results(results)
            finished_runs.append(run)
            results_by_run[run.id] = results

        final_status = "completed"
        if any(r.status == "ERROR" for r in finished_runs):
            final_status = "failed"
        experiment = Experiment(
            id=experiment.id,
            project_id=experiment.project_id,
            name=experiment.name,
            dataset_id=experiment.dataset_id,
            model_config=dict(experiment.model_config),
            version=experiment.version,
            baseline_experiment_id=experiment.baseline_experiment_id,
            status=final_status,
            created_at=experiment.created_at,
            app_config_id=experiment.app_config_id,
            metrics_set_id=experiment.metrics_set_id,
        )
        experiment = await self._experiments.update(experiment)

        return EvaluateExperimentResult(
            experiment=experiment,
            runs=finished_runs,
            results_by_run=results_by_run,
        )


@dataclass(frozen=True, slots=True)
class ScoreExperimentFromPackCommand:
    experiment_id: uuid.UUID
    metrics_set_id: uuid.UUID | None = None
    save_as_default: bool = False


class ScoreExperimentFromPack:
    def __init__(
        self,
        experiments: ExperimentRepository,
        resolve_metrics_set: ResolveMetricsSetForScore,
        evaluate_experiment: EvaluateExperiment,
    ) -> None:
        self._experiments = experiments
        self._resolve = resolve_metrics_set
        self._evaluate_experiment = evaluate_experiment

    async def execute(self, command: ScoreExperimentFromPackCommand) -> EvaluateExperimentResult:
        experiment = await self._experiments.get_by_id(command.experiment_id)
        if experiment is None:
            raise ExperimentNotFoundError(command.experiment_id)

        resolved = await self._resolve.execute(
            experiment=experiment,
            metrics_set_id=command.metrics_set_id,
            save_as_default=command.save_as_default,
        )

        enabled = [e for e in resolved.entries if e.enabled and e.evaluator_id is not None]
        try:
            # Guards sets saved before the invariant existed: thresholds and overrides
            # below are keyed by evaluator, so a shared evaluator would mix two entries.
            assert_unique_evaluator_ids(tuple(enabled))
        except ValueError as exc:
            raise MetricsSetValidationError(str(exc)) from exc

        evaluator_ids: list[uuid.UUID] = []
        pass_thresholds: dict[uuid.UUID, float | None] = {}
        config_overrides: dict[uuid.UUID, dict[str, Any]] = {}
        for entry in enabled:
            if entry.evaluator_id is None:
                continue
            evaluator_ids.append(entry.evaluator_id)
            pass_thresholds[entry.evaluator_id] = entry.threshold
            # Evaluators are shared per kind across metrics sets; the entry config
            # (k, max_ms, model, ...) is what this metrics set asks for.
            config_overrides[entry.evaluator_id] = dict(entry.config)
        return await self._evaluate_experiment.execute(
            EvaluateExperimentCommand(
                experiment_id=command.experiment_id,
                evaluator_ids=evaluator_ids,
                pass_thresholds=pass_thresholds,
                config_overrides=config_overrides,
            )
        )


class ListExperimentRuns:
    def __init__(self, runs: EvaluationRunRepository) -> None:
        self._runs = runs

    async def execute(self, experiment_id: uuid.UUID) -> list[EvaluationRun]:
        return await self._runs.list_runs_by_experiment(experiment_id)


class GetEvaluationRun:
    def __init__(
        self,
        runs: EvaluationRunRepository,
        experiments: ExperimentRepository,
    ) -> None:
        self._runs = runs
        self._experiments = experiments

    async def execute(
        self, run_id: uuid.UUID
    ) -> tuple[EvaluationRun, list[EvaluationResultRecord]]:
        run = await self._runs.get_run(run_id)
        if run is None:
            raise EvaluationRunNotFoundError(run_id)
        results = await self._runs.list_results(run_id)
        return run, results


class EvaluationRunNotFoundError(Exception):
    def __init__(self, run_id: uuid.UUID) -> None:
        self.run_id = run_id
        super().__init__(f"Evaluation run not found: {run_id}")
