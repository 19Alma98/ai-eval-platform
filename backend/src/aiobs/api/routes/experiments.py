from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from aiobs.api.deps import (
    get_create_experiment,
    get_evaluate_experiment,
    get_get_experiment,
    get_list_experiment_runs,
    get_list_experiments,
)
from aiobs.api.deps import (
    get_evaluation_run as get_evaluation_run_use_case,
)
from aiobs.api.schemas import (
    CreateExperimentRequest,
    EvaluateRequest,
    EvaluateResponse,
    EvaluationResultResponse,
    EvaluationRunResponse,
    ExperimentResponse,
)
from aiobs.application.datasets import DatasetNotFoundError
from aiobs.application.evaluate import (
    EmptyEvaluatorListError,
    EvaluateExperiment,
    EvaluateExperimentCommand,
    EvaluationRunNotFoundError,
    GetEvaluationRun,
    ListExperimentRuns,
)
from aiobs.application.evaluators import EvaluatorNotFoundError
from aiobs.application.experiments import (
    CreateExperiment,
    CreateExperimentCommand,
    ExperimentNotFoundError,
    GetExperiment,
    ListExperiments,
)
from aiobs.application.projects import ProjectNotFoundError
from aiobs.domain.evaluation import EvaluationResultRecord, EvaluationRun
from aiobs.domain.experiment import Experiment

router = APIRouter(tags=["experiments"])


def _experiment_response(experiment: Experiment) -> ExperimentResponse:
    return ExperimentResponse.model_validate(
        {
            "id": experiment.id,
            "project_id": experiment.project_id,
            "name": experiment.name,
            "dataset_id": experiment.dataset_id,
            "model_config": dict(experiment.model_config),
            "application_version": experiment.application_version,
            "baseline_experiment_id": experiment.baseline_experiment_id,
            "status": experiment.status,
            "created_at": experiment.created_at,
        }
    )


def _result_response(result: EvaluationResultRecord) -> EvaluationResultResponse:
    return EvaluationResultResponse(
        id=result.id,
        run_id=result.run_id,
        dataset_item_id=result.dataset_item_id,
        score=result.score,
        label=result.label,
        explanation=result.explanation,
        metadata=result.metadata,
        duration_ms=result.duration_ms,
    )


def _run_response(
    run: EvaluationRun, results: list[EvaluationResultRecord] | None = None
) -> EvaluationRunResponse:
    return EvaluationRunResponse(
        id=run.id,
        experiment_id=run.experiment_id,
        evaluator_id=run.evaluator_id,
        status=run.status,
        started_at=run.started_at,
        finished_at=run.finished_at,
        metadata=run.metadata,
        results=[_result_response(r) for r in (results or [])],
    )


@router.post(
    "/api/v1/projects/{project_id}/experiments",
    response_model=ExperimentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_experiment(
    project_id: uuid.UUID,
    body: CreateExperimentRequest,
    use_case: CreateExperiment = Depends(get_create_experiment),
) -> ExperimentResponse:
    try:
        experiment = await use_case.execute(
            CreateExperimentCommand(
                project_id=project_id,
                name=body.name,
                dataset_id=body.dataset_id,
                model_config=body.experiment_model_config,
                application_version=body.application_version,
                baseline_experiment_id=body.baseline_experiment_id,
            )
        )
    except (ProjectNotFoundError, DatasetNotFoundError, ExperimentNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _experiment_response(experiment)


@router.get(
    "/api/v1/projects/{project_id}/experiments",
    response_model=list[ExperimentResponse],
)
async def list_experiments(
    project_id: uuid.UUID,
    use_case: ListExperiments = Depends(get_list_experiments),
) -> list[ExperimentResponse]:
    experiments = await use_case.execute(project_id)
    return [_experiment_response(e) for e in experiments]


@router.get("/api/v1/experiments/{experiment_id}", response_model=ExperimentResponse)
async def get_experiment(
    experiment_id: uuid.UUID,
    use_case: GetExperiment = Depends(get_get_experiment),
) -> ExperimentResponse:
    try:
        experiment = await use_case.execute(experiment_id)
    except ExperimentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _experiment_response(experiment)


@router.post(
    "/api/v1/experiments/{experiment_id}/evaluate",
    response_model=EvaluateResponse,
)
async def evaluate_experiment(
    experiment_id: uuid.UUID,
    body: EvaluateRequest,
    use_case: EvaluateExperiment = Depends(get_evaluate_experiment),
) -> EvaluateResponse:
    try:
        outcome = await use_case.execute(
            EvaluateExperimentCommand(
                experiment_id=experiment_id,
                evaluator_ids=body.evaluator_ids,
            )
        )
    except (
        ExperimentNotFoundError,
        EvaluatorNotFoundError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except EmptyEvaluatorListError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return EvaluateResponse(
        experiment=_experiment_response(outcome.experiment),
        runs=[_run_response(run, outcome.results_by_run.get(run.id, [])) for run in outcome.runs],
    )


@router.get(
    "/api/v1/experiments/{experiment_id}/runs",
    response_model=list[EvaluationRunResponse],
)
async def list_experiment_runs(
    experiment_id: uuid.UUID,
    use_case: ListExperimentRuns = Depends(get_list_experiment_runs),
) -> list[EvaluationRunResponse]:
    runs = await use_case.execute(experiment_id)
    return [_run_response(run) for run in runs]


@router.get(
    "/api/v1/evaluation-runs/{run_id}",
    response_model=EvaluationRunResponse,
)
async def get_evaluation_run_detail(
    run_id: uuid.UUID,
    use_case: GetEvaluationRun = Depends(get_evaluation_run_use_case),
) -> EvaluationRunResponse:
    try:
        run, results = await use_case.execute(run_id)
    except EvaluationRunNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _run_response(run, results)
