from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from opengrade_server.application.evaluators import EvaluatorNotFoundError
from opengrade_server.application.experiments import ExperimentNotFoundError
from opengrade_server.application.metrics_sets import (
    MetricsSetValidationError,
    ResolveMetricsSetForScore,
)
from opengrade_server.application.scoring_inputs import INPUTS_FINGERPRINT_KEY, load_scoring_inputs
from opengrade_server.domain.evaluation import EvaluationResultRecord, EvaluationRun
from opengrade_server.domain.experiment import Experiment
from opengrade_server.domain.metrics_set import assert_unique_evaluator_ids
from opengrade_server.domain.repositories import (
    DatasetRepository,
    EvaluationRunRepository,
    EvaluatorRepository,
    ExperimentItemOutputRepository,
    ExperimentRepository,
)
from opengrade_server.evaluation.runner import EvaluationRunner

logger = logging.getLogger(__name__)


class EmptyEvaluatorListError(Exception):
    def __init__(self) -> None:
        super().__init__("evaluator_ids must not be empty")


class ClientEvaluatorNotRunnableError(Exception):
    def __init__(self, evaluator_id: uuid.UUID) -> None:
        self.evaluator_id = evaluator_id
        super().__init__(
            f"Evaluator {evaluator_id} holds client-submitted scores and cannot be run "
            "by the server; submit them via /client-results"
        )


class ExperimentAlreadyRunningError(Exception):
    def __init__(self, experiment_id: uuid.UUID) -> None:
        self.experiment_id = experiment_id
        super().__init__(f"Experiment is already running: {experiment_id}")


@dataclass(frozen=True, slots=True)
class EvaluateExperimentCommand:
    experiment_id: uuid.UUID
    evaluator_ids: list[uuid.UUID]
    pass_thresholds: dict[uuid.UUID, float | None] | None = None
    config_overrides: dict[uuid.UUID, dict[str, Any]] | None = None
    mark_running: bool = True


@dataclass(frozen=True, slots=True)
class EvaluateExperimentResult:
    experiment: Experiment
    runs: list[EvaluationRun]
    results_by_run: dict[uuid.UUID, list[EvaluationResultRecord]]


@dataclass(frozen=True, slots=True)
class StartEvaluateResult:
    experiment: Experiment
    command: EvaluateExperimentCommand


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

        if command.mark_running:
            claimed = await self._experiments.try_mark_running(command.experiment_id)
            if claimed is None:
                current = await self._experiments.get_by_id(command.experiment_id)
                if current is None:
                    raise ExperimentNotFoundError(command.experiment_id)
                raise ExperimentAlreadyRunningError(command.experiment_id)
            experiment = claimed
        elif experiment.status != "running":
            claimed = await self._experiments.try_mark_running(command.experiment_id)
            if claimed is not None:
                experiment = claimed

        finished_runs: list[EvaluationRun] = []
        results_by_run: dict[uuid.UUID, list[EvaluationResultRecord]] = {}

        try:
            inputs = await load_scoring_inputs(experiment, self._datasets, self._outputs)
            merged_items = inputs.items
            missing_output_item_ids = inputs.missing_output_item_ids
            evaluator_entities = await self._evaluators.get_by_ids(command.evaluator_ids)
            by_id = {e.id: e for e in evaluator_entities}
            missing = [eid for eid in command.evaluator_ids if eid not in by_id]
            if missing:
                raise EvaluatorNotFoundError(missing[0])
            for entity in evaluator_entities:
                if entity.project_id != experiment.project_id:
                    raise EvaluatorNotFoundError(entity.id)

            for evaluator_id in command.evaluator_ids:
                entity = by_id[evaluator_id]
                run = EvaluationRun.create(
                    experiment.id,
                    entity.id,
                    status="PENDING",
                    metadata={INPUTS_FINGERPRINT_KEY: inputs.fingerprint},
                )
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
            experiment = await self._experiments.update(experiment.with_status(final_status))
        except Exception as exc:
            logger.exception("Experiment scoring failed: %s", command.experiment_id)
            await self._fail_in_flight_runs(command.experiment_id, str(exc))
            experiment = await self._experiments.get_by_id(command.experiment_id)
            if experiment is not None and experiment.status == "running":
                experiment = await self._experiments.update(experiment.with_status("failed"))
            raise

        return EvaluateExperimentResult(
            experiment=experiment,
            runs=finished_runs,
            results_by_run=results_by_run,
        )

    async def _fail_in_flight_runs(self, experiment_id: uuid.UUID, error_message: str) -> None:
        now = datetime.now(UTC)
        note = error_message[:500]
        runs = await self._runs.list_runs_by_experiment(experiment_id)
        for run in runs:
            if run.status not in {"PENDING", "RUNNING"}:
                continue
            metadata = dict(run.metadata)
            metadata["error"] = note
            await self._runs.update_run(
                run.with_status("ERROR", finished_at=now, metadata=metadata)
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
        started = await self.start(command)
        return await self._evaluate_experiment.execute(started.command)

    async def start(self, command: ScoreExperimentFromPackCommand) -> StartEvaluateResult:
        """Resolve pack, mark experiment running, return command for background scoring."""
        experiment = await self._experiments.get_by_id(command.experiment_id)
        if experiment is None:
            raise ExperimentNotFoundError(command.experiment_id)
        if experiment.status == "running":
            raise ExperimentAlreadyRunningError(experiment.id)

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

        if not evaluator_ids:
            raise EmptyEvaluatorListError()

        claimed = await self._experiments.try_mark_running(command.experiment_id)
        if claimed is None:
            current = await self._experiments.get_by_id(command.experiment_id)
            if current is None:
                raise ExperimentNotFoundError(command.experiment_id)
            raise ExperimentAlreadyRunningError(command.experiment_id)
        experiment = claimed

        return StartEvaluateResult(
            experiment=experiment,
            command=EvaluateExperimentCommand(
                experiment_id=command.experiment_id,
                evaluator_ids=evaluator_ids,
                pass_thresholds=pass_thresholds,
                config_overrides=config_overrides,
                mark_running=False,
            ),
        )


class StartEvaluateExperiment:
    """Validate evaluators, mark running, return command for background scoring."""

    def __init__(
        self,
        experiments: ExperimentRepository,
        evaluators: EvaluatorRepository,
    ) -> None:
        self._experiments = experiments
        self._evaluators = evaluators

    async def execute(self, command: EvaluateExperimentCommand) -> StartEvaluateResult:
        if not command.evaluator_ids:
            raise EmptyEvaluatorListError()

        experiment = await self._experiments.get_by_id(command.experiment_id)
        if experiment is None:
            raise ExperimentNotFoundError(command.experiment_id)
        if experiment.status == "running":
            raise ExperimentAlreadyRunningError(experiment.id)

        evaluator_entities = await self._evaluators.get_by_ids(command.evaluator_ids)
        by_id = {e.id: e for e in evaluator_entities}
        missing = [eid for eid in command.evaluator_ids if eid not in by_id]
        if missing:
            raise EvaluatorNotFoundError(missing[0])
        for entity in evaluator_entities:
            if entity.project_id != experiment.project_id:
                raise EvaluatorNotFoundError(entity.id)
            if entity.is_client:
                raise ClientEvaluatorNotRunnableError(entity.id)

        claimed = await self._experiments.try_mark_running(command.experiment_id)
        if claimed is None:
            current = await self._experiments.get_by_id(command.experiment_id)
            if current is None:
                raise ExperimentNotFoundError(command.experiment_id)
            raise ExperimentAlreadyRunningError(command.experiment_id)
        experiment = claimed
        return StartEvaluateResult(
            experiment=experiment,
            command=EvaluateExperimentCommand(
                experiment_id=command.experiment_id,
                evaluator_ids=list(command.evaluator_ids),
                pass_thresholds=command.pass_thresholds,
                config_overrides=command.config_overrides,
                mark_running=False,
            ),
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


async def schedule_evaluate_experiment(command: EvaluateExperimentCommand) -> None:
    """BackgroundTasks entrypoint — opens a dedicated DB session."""
    from opengrade_server.config import get_settings
    from opengrade_server.evaluation.runner import EvaluationRunner
    from opengrade_server.infrastructure.db import try_get_session_factory
    from opengrade_server.infrastructure.repositories import (
        SqlAlchemyDatasetRepository,
        SqlAlchemyEvaluationRunRepository,
        SqlAlchemyEvaluatorRepository,
        SqlAlchemyExperimentItemOutputRepository,
        SqlAlchemyExperimentRepository,
    )

    factory = try_get_session_factory()
    if factory is None:
        logger.warning(
            "Skipping background experiment score; DB session factory not initialized (%s)",
            command.experiment_id,
        )
        return

    settings = get_settings()
    async with factory() as session:
        experiments = SqlAlchemyExperimentRepository(session)
        datasets = SqlAlchemyDatasetRepository(session)
        evaluators = SqlAlchemyEvaluatorRepository(session)
        runs = SqlAlchemyEvaluationRunRepository(session)
        outputs = SqlAlchemyExperimentItemOutputRepository(session)
        scorer = EvaluateExperiment(
            experiments,
            datasets,
            evaluators,
            runs,
            EvaluationRunner(max_concurrency=settings.llm_max_concurrency),
            outputs,
        )
        try:
            await scorer.execute(command)
        except Exception:
            logger.exception("Background experiment score failed: %s", command.experiment_id)
