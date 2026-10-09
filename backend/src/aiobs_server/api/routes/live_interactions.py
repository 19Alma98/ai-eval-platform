from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse

from aiobs_server.api.deps import (
    get_get_live_interaction,
    get_list_live_interactions,
    get_promote_live_interaction,
    get_score_live_interaction,
    get_submit_live_interaction,
    get_summarize_live_judge_calibration,
    get_upsert_live_review,
    get_upsert_live_score_review,
)
from aiobs_server.api.schemas import (
    DatasetItemResponse,
    JudgeCalibrationBucketResponse,
    ListLiveInteractionsResponse,
    LiveInteractionResponse,
    LiveInteractionScoreResponse,
    LiveJudgeWarningResponse,
    LiveReviewResponse,
    LiveScoreReviewResponse,
    PromoteLiveInteractionRequest,
    SubmitLiveInteractionRequest,
    UpsertLiveReviewRequest,
    UpsertLiveScoreReviewRequest,
)
from aiobs_server.application.datasets import DatasetNotFoundError
from aiobs_server.application.live_interactions import (
    GetLiveInteraction,
    ListLiveInteractions,
    ListLiveInteractionsResult,
    LiveInteractionDetail,
    LiveInteractionNotFoundError,
    LiveJudgeWarning,
    LiveScoreNotFoundError,
    PromoteLiveInteraction,
    PromoteLiveInteractionCommand,
    ScoreLiveInteraction,
    SubmitLiveInteraction,
    SubmitLiveInteractionCommand,
    UpsertLiveReview,
    UpsertLiveReviewCommand,
    UpsertLiveScoreReview,
    UpsertLiveScoreReviewCommand,
    schedule_live_score,
)
from aiobs_server.application.live_judge_calibration import (
    JudgeCalibrationBucket,
    SummarizeLiveJudgeCalibration,
)
from aiobs_server.application.metrics_sets import MetricsSetNotFoundError
from aiobs_server.application.projects import ProjectNotFoundError
from aiobs_server.domain.dataset import DatasetItem
from aiobs_server.domain.live_interaction import (
    LiveInteraction,
    LiveInteractionScore,
    LiveReview,
    LiveScoreReview,
)

router = APIRouter(tags=["live-interactions"])


def _score_review_response(review: LiveScoreReview) -> LiveScoreReviewResponse:
    return LiveScoreReviewResponse.model_validate(
        {
            "id": review.id,
            "live_interaction_score_id": review.live_interaction_score_id,
            "verdict": review.verdict,
            "corrected_explanation": review.corrected_explanation,
            "note": review.note,
            "reviewer": review.reviewer,
            "created_at": review.created_at,
        }
    )


def _score_response(
    score: LiveInteractionScore,
    *,
    review: LiveScoreReview | None = None,
) -> LiveInteractionScoreResponse:
    return LiveInteractionScoreResponse.model_validate(
        {
            "id": score.id,
            "live_interaction_id": score.live_interaction_id,
            "evaluator_id": score.evaluator_id,
            "kind": score.kind,
            "score": score.score,
            "label": score.label,
            "explanation": score.explanation,
            "threshold": score.threshold,
            "created_at": score.created_at,
            "metadata": score.metadata,
            "review": _score_review_response(review) if review is not None else None,
        }
    )


def _review_response(review: LiveReview) -> LiveReviewResponse:
    return LiveReviewResponse.model_validate(
        {
            "id": review.id,
            "live_interaction_id": review.live_interaction_id,
            "verdict": review.verdict,
            "note": review.note,
            "reviewer": review.reviewer,
            "created_at": review.created_at,
        }
    )


def _interaction_response(
    interaction: LiveInteraction,
    *,
    scores: list[LiveInteractionScore] | None = None,
    review: LiveReview | None = None,
    score_reviews: dict[uuid.UUID, LiveScoreReview] | None = None,
) -> LiveInteractionResponse:
    reviews = score_reviews or {}
    return LiveInteractionResponse.model_validate(
        {
            "id": interaction.id,
            "project_id": interaction.project_id,
            "question": interaction.question,
            "answer": interaction.answer,
            "documents": interaction.documents,
            "metadata": interaction.metadata,
            "external_id": interaction.external_id,
            "judge_status": interaction.judge_status,
            "metrics_set_id": interaction.metrics_set_id,
            "score_warning": interaction.score_warning,
            "error_message": interaction.error_message,
            "created_at": interaction.created_at,
            "scored_at": interaction.scored_at,
            "scores": [_score_response(s, review=reviews.get(s.id)) for s in (scores or [])],
            "review": _review_response(review) if review is not None else None,
        }
    )


def _detail_response(detail: LiveInteractionDetail) -> LiveInteractionResponse:
    return _interaction_response(
        detail.interaction,
        scores=detail.scores,
        review=detail.review,
        score_reviews=detail.score_reviews,
    )


def _item_response(item: DatasetItem) -> DatasetItemResponse:
    return DatasetItemResponse.model_validate(
        {
            "id": item.id,
            "dataset_id": item.dataset_id,
            "input": item.input,
            "expected_output": item.expected_output,
            "actual_output": item.actual_output,
            "context": item.context,
            "metadata": item.metadata,
            "source_trace_id": item.source_trace_id,
            "source_span_id": item.source_span_id,
        }
    )


def _calibration_response(bucket: JudgeCalibrationBucket) -> JudgeCalibrationBucketResponse:
    return JudgeCalibrationBucketResponse.model_validate(
        {
            "kind": bucket.kind,
            "model": bucket.model,
            "method": bucket.method,
            "prompt_version": bucket.prompt_version,
            "n_reviewed": bucket.n_reviewed,
            "n_agree": bucket.n_agree,
            "n_disagree": bucket.n_disagree,
            "agreement_rate": bucket.agreement_rate,
            "n_explanation_edits": bucket.n_explanation_edits,
            "explanation_edit_rate": bucket.explanation_edit_rate,
        }
    )


@router.post(
    "/api/v1/projects/{project_id}/live-interactions",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=LiveInteractionResponse,
)
async def submit_live_interaction(
    project_id: uuid.UUID,
    body: SubmitLiveInteractionRequest,
    background_tasks: BackgroundTasks,
    use_case: SubmitLiveInteraction = Depends(get_submit_live_interaction),
) -> JSONResponse:
    try:
        result = await use_case.execute(
            SubmitLiveInteractionCommand(
                project_id=project_id,
                question=body.question,
                answer=body.answer,
                documents=body.documents,
                metadata=body.metadata,
                external_id=body.external_id,
                metrics_set_id=body.metrics_set_id,
            )
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MetricsSetNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if result.created:
        background_tasks.add_task(schedule_live_score, result.interaction.id)

    payload = _interaction_response(result.interaction).model_dump(mode="json")
    return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=payload)


@router.get(
    "/api/v1/projects/{project_id}/live-interactions/calibration",
    response_model=list[JudgeCalibrationBucketResponse],
)
async def live_judge_calibration(
    project_id: uuid.UUID,
    since: datetime | None = Query(default=None),
    use_case: SummarizeLiveJudgeCalibration = Depends(get_summarize_live_judge_calibration),
) -> list[JudgeCalibrationBucketResponse]:
    try:
        buckets = await use_case.execute(project_id, since=since)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [_calibration_response(b) for b in buckets]


def _judge_warning_response(warning: LiveJudgeWarning) -> LiveJudgeWarningResponse:
    return LiveJudgeWarningResponse(
        kind=warning.kind,
        warnings=list(warning.warnings),
        warning_detail=dict(warning.warning_detail),
    )


def _list_response(result: ListLiveInteractionsResult) -> ListLiveInteractionsResponse:
    return ListLiveInteractionsResponse(
        items=[
            _interaction_response(
                interaction,
                scores=scores,
                review=review,
                score_reviews=score_reviews,
            )
            for interaction, scores, review, score_reviews in result.items
        ],
        judge_warnings=[_judge_warning_response(w) for w in result.judge_warnings],
    )


@router.get(
    "/api/v1/projects/{project_id}/live-interactions",
    response_model=ListLiveInteractionsResponse,
)
async def list_live_interactions(
    project_id: uuid.UUID,
    judge_status: str | None = Query(default=None),
    search: str | None = Query(default=None),
    failed_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    use_case: ListLiveInteractions = Depends(get_list_live_interactions),
) -> ListLiveInteractionsResponse:
    result = await use_case.execute(
        project_id,
        judge_status=judge_status,
        search=search,
        failed_only=failed_only,
        limit=limit,
    )
    return _list_response(result)


@router.get(
    "/api/v1/live-interactions/{interaction_id}",
    response_model=LiveInteractionResponse,
)
async def get_live_interaction(
    interaction_id: uuid.UUID,
    use_case: GetLiveInteraction = Depends(get_get_live_interaction),
) -> LiveInteractionResponse:
    try:
        detail = await use_case.execute(interaction_id)
    except LiveInteractionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _detail_response(detail)


@router.post(
    "/api/v1/live-interactions/{interaction_id}/review",
    response_model=LiveReviewResponse,
)
async def upsert_live_review(
    interaction_id: uuid.UUID,
    body: UpsertLiveReviewRequest,
    use_case: UpsertLiveReview = Depends(get_upsert_live_review),
) -> LiveReviewResponse:
    try:
        review = await use_case.execute(
            UpsertLiveReviewCommand(
                interaction_id=interaction_id,
                verdict=body.verdict,
                note=body.note,
                reviewer=body.reviewer,
            )
        )
    except LiveInteractionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _review_response(review)


@router.post(
    "/api/v1/live-interaction-scores/{score_id}/review",
    response_model=LiveScoreReviewResponse,
)
async def upsert_live_score_review(
    score_id: uuid.UUID,
    body: UpsertLiveScoreReviewRequest,
    use_case: UpsertLiveScoreReview = Depends(get_upsert_live_score_review),
) -> LiveScoreReviewResponse:
    try:
        review = await use_case.execute(
            UpsertLiveScoreReviewCommand(
                score_id=score_id,
                verdict=body.verdict,
                corrected_explanation=body.corrected_explanation,
                note=body.note,
                reviewer=body.reviewer,
            )
        )
    except LiveScoreNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _score_review_response(review)


@router.post(
    "/api/v1/live-interactions/{interaction_id}/promote",
    response_model=DatasetItemResponse,
    status_code=status.HTTP_201_CREATED,
)
async def promote_live_interaction(
    interaction_id: uuid.UUID,
    body: PromoteLiveInteractionRequest,
    use_case: PromoteLiveInteraction = Depends(get_promote_live_interaction),
) -> DatasetItemResponse:
    try:
        item = await use_case.execute(
            PromoteLiveInteractionCommand(
                interaction_id=interaction_id,
                dataset_id=body.dataset_id,
                expected_output=body.expected_output,
                expected_doc_ids=body.expected_doc_ids,
            )
        )
    except LiveInteractionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DatasetNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _item_response(item)


@router.post(
    "/api/v1/live-interactions/{interaction_id}/rescore",
    response_model=LiveInteractionResponse,
)
async def rescore_live_interaction(
    interaction_id: uuid.UUID,
    score: ScoreLiveInteraction = Depends(get_score_live_interaction),
    get_detail: GetLiveInteraction = Depends(get_get_live_interaction),
) -> LiveInteractionResponse:
    try:
        await score.execute(interaction_id)
        detail = await get_detail.execute(interaction_id)
    except LiveInteractionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _detail_response(detail)
