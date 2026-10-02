from __future__ import annotations

import uuid
from dataclasses import dataclass

from aiobs.application.evaluators import EvaluatorNotFoundError
from aiobs.application.experiment_outputs import merge_dataset_item
from aiobs.application.experiments import ExperimentNotFoundError
from aiobs.domain.evaluation import EvaluationResultRecord, EvaluationRun
from aiobs.domain.experiment import Experiment
from aiobs.domain.repositories import (
    DatasetRepository,
    EvaluationRunRepository,
    EvaluatorRepository,
    ExperimentItemOutputRepository,
    ExperimentRepository,
)
from aiobs.evaluation.runner import EvaluationRunner


class EmptyEvaluatorListError(Exception):
    def __init__(self) -> None:
        super().__init__("evaluator_ids must not be empty")


@dataclass(frozen=True, slots=True)
class EvaluateExperimentCommand:
    experiment_id: uuid.UUID
    evaluator_ids: list[uuid.UUID]


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
        merged_items = [
            merge_dataset_item(item, by_item.get(item.id)) for item in items
        ]
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
        )
        experiment = await self._experiments.update(experiment)

        finished_runs: list[EvaluationRun] = []
        results_by_run: dict[uuid.UUID, list[EvaluationResultRecord]] = {}

        for evaluator_id in command.evaluator_ids:
            entity = by_id[evaluator_id]
            run = EvaluationRun.create(experiment.id, entity.id, status="PENDING")
            run = await self._runs.add_run(run)
            run, results = await self._runner.run_evaluator(
                run=run, evaluator_entity=entity, items=merged_items
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
        )
        experiment = await self._experiments.update(experiment)

        return EvaluateExperimentResult(
            experiment=experiment,
            runs=finished_runs,
            results_by_run=results_by_run,
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
