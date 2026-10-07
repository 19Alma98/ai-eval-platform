from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse

from aiobs.api.deps import (
    get_get_live_interaction,
    get_list_live_interactions,
    get_promote_live_interaction,
    get_score_live_interaction,
    get_submit_live_interaction,
    get_upsert_live_review,
)
from aiobs.api.schemas import (
    DatasetItemResponse,
    LiveInteractionResponse,
    LiveInteractionScoreResponse,
    LiveReviewResponse,
    PromoteLiveInteractionRequest,
    SubmitLiveInteractionRequest,
    UpsertLiveReviewRequest,
)
from aiobs.application.datasets import DatasetNotFoundError
from aiobs.application.live_interactions import (
    GetLiveInteraction,
    ListLiveInteractions,
    LiveInteractionDetail,
    LiveInteractionNotFoundError,
    PromoteLiveInteraction,
    PromoteLiveInteractionCommand,
    ScoreLiveInteraction,
    SubmitLiveInteraction,
    SubmitLiveInteractionCommand,
    UpsertLiveReview,
    UpsertLiveReviewCommand,
    schedule_live_score,
)
from aiobs.application.metrics_sets import MetricsSetNotFoundError
from aiobs.application.projects import ProjectNotFoundError
from aiobs.domain.dataset import DatasetItem
from aiobs.domain.live_interaction import LiveInteraction, LiveInteractionScore, LiveReview

router = APIRouter(tags=["live-interactions"])


def _score_response(score: LiveInteractionScore) -> LiveInteractionScoreResponse:
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
) -> LiveInteractionResponse:
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
            "scores": [_score_response(s) for s in (scores or [])],
            "review": _review_response(review) if review is not None else None,
        }
    )


def _detail_response(detail: LiveInteractionDetail) -> LiveInteractionResponse:
    return _interaction_response(
        detail.interaction,
        scores=detail.scores,
        review=detail.review,
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
    "/api/v1/projects/{project_id}/live-interactions",
    response_model=list[LiveInteractionResponse],
)
async def list_live_interactions(
    project_id: uuid.UUID,
    judge_status: str | None = Query(default=None),
    search: str | None = Query(default=None),
    failed_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    use_case: ListLiveInteractions = Depends(get_list_live_interactions),
) -> list[LiveInteractionResponse]:
    rows = await use_case.execute(
        project_id,
        judge_status=judge_status,
        search=search,
        failed_only=failed_only,
        limit=limit,
    )
    return [
        _interaction_response(interaction, scores=scores, review=review)
        for interaction, scores, review in rows
    ]


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
