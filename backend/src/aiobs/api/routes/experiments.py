from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status

from aiobs.api.deps import (
    get_compare_experiment_items,
    get_compare_experiments,
    get_create_experiment,
    get_evaluate_experiment,
    get_get_experiment,
    get_list_experiment_outputs,
    get_list_experiment_runs,
    get_list_experiments,
    get_score_experiment_from_pack,
    get_summarize_experiment,
    get_upsert_experiment_outputs,
)
from aiobs.api.deps import (
    get_evaluation_run as get_evaluation_run_use_case,
)
from aiobs.api.schemas import (
    CompareRunRefResponse,
    CreateExperimentRequest,
    EvaluatePackRequest,
    EvaluateRequest,
    EvaluateResponse,
    EvaluationResultResponse,
    EvaluationRunResponse,
    EvaluatorSummaryResponse,
    ExperimentCompareResponse,
    ExperimentItemCompareResponse,
    ExperimentItemOutputResponse,
    ExperimentResponse,
    ExperimentSummaryResponse,
    ItemComparisonRowResponse,
    ItemSideResponse,
    MetricComparisonResponse,
    UpsertExperimentOutputItemRequest,
    UpsertExperimentOutputsRequest,
    UpsertExperimentOutputsResponse,
)
from aiobs.application.app_configs import AppConfigNotFoundError
from aiobs.application.compare import (
    CompareExperiments,
    CompareRunRef,
    ExperimentComparison,
    ExperimentSummary,
    InvalidCompareSelectionError,
    SummarizeExperiment,
)
from aiobs.application.compare_items import (
    AmbiguousEvaluatorError,
    CompareExperimentItems,
    DatasetMismatchError,
    ItemComparisonResult,
    ItemComparisonRow,
    ItemSide,
)
from aiobs.application.datasets import DatasetNotFoundError
from aiobs.application.evaluate import (
    EmptyEvaluatorListError,
    EvaluateExperiment,
    EvaluateExperimentCommand,
    EvaluationRunNotFoundError,
    GetEvaluationRun,
    ListExperimentRuns,
    ScoreExperimentFromPack,
    ScoreExperimentFromPackCommand,
)
from aiobs.application.evaluators import EvaluatorNotFoundError
from aiobs.application.experiment_outputs import (
    ExperimentItemNotInDatasetError,
    ListExperimentOutputs,
    UpsertExperimentOutputs,
    UpsertOutputItem,
)
from aiobs.application.experiments import (
    CreateExperiment,
    CreateExperimentCommand,
    ExperimentNotFoundError,
    GetExperiment,
    ListExperiments,
)
from aiobs.application.metrics_sets import MetricsSetNotFoundError, MetricsSetValidationError
from aiobs.application.projects import ProjectNotFoundError
from aiobs.domain.evaluation import EvaluationResultRecord, EvaluationRun
from aiobs.domain.experiment import Experiment
from aiobs.domain.experiment_output import UNSET, ExperimentItemOutput
from aiobs.regression.aggregate import MetricComparison

router = APIRouter(tags=["experiments"])


def _experiment_response(experiment: Experiment) -> ExperimentResponse:
    return ExperimentResponse.model_validate(
        {
            "id": experiment.id,
            "project_id": experiment.project_id,
            "name": experiment.name,
            "dataset_id": experiment.dataset_id,
            "model_config": dict(experiment.model_config),
            "version": experiment.version,
            "baseline_experiment_id": experiment.baseline_experiment_id,
            "app_config_id": experiment.app_config_id,
            "metrics_set_id": experiment.metrics_set_id,
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


def _summary_response(summary: ExperimentSummary) -> ExperimentSummaryResponse:
    return ExperimentSummaryResponse(
        experiment_id=summary.experiment_id,
        evaluators=[
            EvaluatorSummaryResponse(
                evaluator_id=item.evaluator_id,
                evaluator_name=item.evaluator_name,
                run_id=item.run_id,
                status=item.status,
                n_items=item.aggregates.n_items,
                n_scored=item.aggregates.n_scored,
                n_error=item.aggregates.n_error,
                n_skipped=item.aggregates.n_skipped,
                mean_score=item.aggregates.mean_score,
                pass_rate=item.aggregates.pass_rate,
            )
            for item in summary.evaluators
        ],
    )


def _metric_response(metric: MetricComparison) -> MetricComparisonResponse:
    return MetricComparisonResponse(
        evaluator_id=metric.evaluator_id,
        evaluator_name=metric.evaluator_name,
        metric=metric.metric,
        candidate=metric.candidate,
        baseline=metric.baseline,
        delta=metric.delta,
        status=metric.status,
    )


def _output_response(output: ExperimentItemOutput) -> ExperimentItemOutputResponse:
    return ExperimentItemOutputResponse(
        id=output.id,
        experiment_id=output.experiment_id,
        dataset_item_id=output.dataset_item_id,
        actual_output=output.actual_output,
        context=output.context,
        metadata=dict(output.metadata),
        updated_at=output.updated_at,
    )


def _upsert_output_item(entry: UpsertExperimentOutputItemRequest) -> UpsertOutputItem:
    fields_set = entry.model_fields_set
    return UpsertOutputItem(
        dataset_item_id=entry.dataset_item_id,
        actual_output=entry.actual_output if "actual_output" in fields_set else UNSET,
        context=entry.context if "context" in fields_set else UNSET,
        metadata=entry.metadata if "metadata" in fields_set else UNSET,
    )


def _compare_run_ref_response(ref: CompareRunRef) -> CompareRunRefResponse:
    return CompareRunRefResponse(
        evaluator_id=ref.evaluator_id,
        run_id=ref.run_id,
        metadata=dict(ref.metadata),
    )


def _compare_response(comparison: ExperimentComparison) -> ExperimentCompareResponse:
    return ExperimentCompareResponse(
        experiment_id=comparison.experiment_id,
        baseline_experiment_id=comparison.baseline_experiment_id,
        metrics=[_metric_response(m) for m in comparison.metrics],
        regressions=[_metric_response(m) for m in comparison.regressions],
        improved=[_metric_response(m) for m in comparison.improved],
        unchanged=[_metric_response(m) for m in comparison.unchanged],
        config_mismatches=[_metric_response(m) for m in comparison.config_mismatches],
        insufficient_n=[_metric_response(m) for m in comparison.insufficient_n],
        candidate_runs=[_compare_run_ref_response(r) for r in comparison.candidate_runs],
        baseline_runs=[_compare_run_ref_response(r) for r in comparison.baseline_runs],
    )


def _item_side_response(side: ItemSide) -> ItemSideResponse:
    return ItemSideResponse(
        actual_output=side.actual_output,
        context=side.context,
        score=side.score,
        label=side.label,
        explanation=side.explanation,
        metadata=side.metadata,
        run_id=side.run_id,
    )


def _item_row_response(row: ItemComparisonRow) -> ItemComparisonRowResponse:
    return ItemComparisonRowResponse(
        dataset_item_id=row.dataset_item_id,
        input=row.input,
        expected_output=row.expected_output,
        baseline=_item_side_response(row.baseline),
        candidate=_item_side_response(row.candidate),
        delta=row.delta,
        status=row.status,
    )


def _compare_items_response(
    comparison: ItemComparisonResult,
) -> ExperimentItemCompareResponse:
    return ExperimentItemCompareResponse(
        experiment_id=comparison.experiment_id,
        baseline_experiment_id=comparison.baseline_experiment_id,
        evaluator_id=comparison.evaluator_id,
        items=[_item_row_response(row) for row in comparison.items],
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
                version=body.version,
                baseline_experiment_id=body.baseline_experiment_id,
                app_config_id=body.app_config_id,
                app_config_alias=body.app_config_alias,
                metrics_set_id=body.metrics_set_id,
            )
        )
    except (
        ProjectNotFoundError,
        DatasetNotFoundError,
        ExperimentNotFoundError,
        AppConfigNotFoundError,
        MetricsSetNotFoundError,
    ) as exc:
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


@router.put(
    "/api/v1/experiments/{experiment_id}/outputs",
    response_model=UpsertExperimentOutputsResponse,
)
async def upsert_experiment_outputs(
    experiment_id: uuid.UUID,
    body: UpsertExperimentOutputsRequest,
    use_case: UpsertExperimentOutputs = Depends(get_upsert_experiment_outputs),
) -> UpsertExperimentOutputsResponse:
    try:
        items = await use_case.execute(
            experiment_id,
            [_upsert_output_item(entry) for entry in body.items],
        )
    except ExperimentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ExperimentItemNotInDatasetError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return UpsertExperimentOutputsResponse(
        upserted=len(items),
        items=[_output_response(item) for item in items],
    )


@router.get(
    "/api/v1/experiments/{experiment_id}/outputs",
    response_model=list[ExperimentItemOutputResponse],
)
async def list_experiment_outputs(
    experiment_id: uuid.UUID,
    use_case: ListExperimentOutputs = Depends(get_list_experiment_outputs),
) -> list[ExperimentItemOutputResponse]:
    try:
        items = await use_case.execute(experiment_id)
    except ExperimentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return [_output_response(item) for item in items]


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


@router.post(
    "/api/v1/experiments/{experiment_id}/evaluate-pack",
    response_model=EvaluateResponse,
)
async def evaluate_experiment_from_pack(
    experiment_id: uuid.UUID,
    body: EvaluatePackRequest | None = None,
    use_case: ScoreExperimentFromPack = Depends(get_score_experiment_from_pack),
) -> EvaluateResponse:
    payload = body or EvaluatePackRequest()
    try:
        outcome = await use_case.execute(
            ScoreExperimentFromPackCommand(
                experiment_id=experiment_id,
                metrics_set_id=payload.metrics_set_id,
                save_as_default=payload.save_as_default,
            )
        )
    except (
        ExperimentNotFoundError,
        EvaluatorNotFoundError,
        ProjectNotFoundError,
        MetricsSetNotFoundError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (EmptyEvaluatorListError, MetricsSetValidationError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return EvaluateResponse(
        experiment=_experiment_response(outcome.experiment),
        runs=[_run_response(run, outcome.results_by_run.get(run.id, [])) for run in outcome.runs],
    )


@router.get(
    "/api/v1/experiments/{experiment_id}/summary",
    response_model=ExperimentSummaryResponse,
)
async def summarize_experiment(
    experiment_id: uuid.UUID,
    run_ids: list[uuid.UUID] | None = Query(default=None),
    evaluator_ids: list[uuid.UUID] | None = Query(default=None),
    use_case: SummarizeExperiment = Depends(get_summarize_experiment),
) -> ExperimentSummaryResponse:
    try:
        summary = await use_case.execute(
            experiment_id,
            run_ids=run_ids,
            evaluator_ids=evaluator_ids,
        )
    except ExperimentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except InvalidCompareSelectionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _summary_response(summary)


@router.get(
    "/api/v1/experiments/{experiment_id}/compare/{baseline_id}",
    response_model=ExperimentCompareResponse,
)
async def compare_experiments(
    experiment_id: uuid.UUID,
    baseline_id: uuid.UUID,
    evaluator_ids: list[uuid.UUID] | None = Query(default=None),
    candidate_run_ids: list[uuid.UUID] | None = Query(default=None),
    baseline_run_ids: list[uuid.UUID] | None = Query(default=None),
    use_case: CompareExperiments = Depends(get_compare_experiments),
) -> ExperimentCompareResponse:
    try:
        comparison = await use_case.execute(
            experiment_id,
            baseline_id,
            evaluator_ids=evaluator_ids,
            candidate_run_ids=candidate_run_ids,
            baseline_run_ids=baseline_run_ids,
        )
    except ExperimentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except InvalidCompareSelectionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _compare_response(comparison)


@router.get(
    "/api/v1/experiments/{experiment_id}/compare/{baseline_id}/items",
    response_model=ExperimentItemCompareResponse,
)
async def compare_experiment_items(
    experiment_id: uuid.UUID,
    baseline_id: uuid.UUID,
    evaluator_id: uuid.UUID | None = Query(default=None),
    regressions_only: bool = Query(default=False),
    use_case: CompareExperimentItems = Depends(get_compare_experiment_items),
) -> ExperimentItemCompareResponse:
    try:
        comparison = await use_case.execute(
            experiment_id,
            baseline_id,
            evaluator_id=evaluator_id,
            regressions_only=regressions_only,
        )
    except ExperimentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (DatasetMismatchError, AmbiguousEvaluatorError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _compare_items_response(comparison)


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
