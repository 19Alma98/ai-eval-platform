from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status

from opengrade_server.api.deps import (
    get_get_conversation,
    get_list_conversations,
    get_promote_conversation,
    get_score_conversation,
)
from opengrade_server.api.schemas import (
    ConversationDetailResponse,
    ConversationListResponse,
    ConversationScoreResponse,
    ConversationSummaryResponse,
    ConversationTurnResponse,
    DatasetItemResponse,
    LiveInteractionResponse,
    PromoteConversationRequest,
)
from opengrade_server.application.conversations import (
    ConversationNotFoundError,
    GetConversation,
    ListConversations,
    PromoteConversation,
    PromoteConversationCommand,
    ScoreConversation,
)
from opengrade_server.application.datasets import DatasetNotFoundError
from opengrade_server.application.projects import ProjectNotFoundError
from opengrade_server.domain.conversation import ConversationScore, ConversationSummary
from opengrade_server.domain.live_interaction import LiveInteraction
from opengrade_server.domain.rag_models import dump_context, dump_dataset_input, dump_metadata

router = APIRouter(prefix="/api/v1/projects/{project_id}/conversations", tags=["conversations"])


def _summary(row: ConversationSummary) -> ConversationSummaryResponse:
    return ConversationSummaryResponse(
        session_id=row.session_id,
        user_id=row.user_id,
        environment=row.environment,
        turn_count=row.turn_count,
        started_at=row.started_at,
        last_activity_at=row.last_activity_at,
        conversation_id=row.conversation_id,
        judge_status=row.judge_status,
        failing_score_kinds=list(row.failing_score_kinds),
    )


def _score(score: ConversationScore) -> ConversationScoreResponse:
    return ConversationScoreResponse(
        id=score.id,
        kind=score.kind,
        score=score.score,
        label=score.label,
        explanation=score.explanation,
        threshold=score.threshold,
        metadata=score.metadata,
        created_at=score.created_at,
    )


def _live(interaction: LiveInteraction) -> LiveInteractionResponse:
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
            "scores": [],
        }
    )


@router.get("", response_model=ConversationListResponse)
async def list_conversations(
    project_id: uuid.UUID,
    since: datetime | None = None,
    until: datetime | None = None,
    user_id: str | None = None,
    environment: str | None = None,
    search: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    use_case: ListConversations = Depends(get_list_conversations),
) -> ConversationListResponse:
    try:
        rows = await use_case.execute(
            project_id,
            since=since,
            until=until,
            user_id=user_id,
            environment=environment,
            search=search,
            limit=limit,
            offset=offset,
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return ConversationListResponse(items=[_summary(r) for r in rows])


@router.get("/{session_id}", response_model=ConversationDetailResponse)
async def get_conversation(
    project_id: uuid.UUID,
    session_id: str,
    use_case: GetConversation = Depends(get_get_conversation),
) -> ConversationDetailResponse:
    try:
        detail = await use_case.execute(project_id, session_id)
    except ProjectNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ConversationNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return ConversationDetailResponse(
        summary=_summary(detail.summary),
        judge_status=detail.conversation.judge_status if detail.conversation else None,
        turns=[
            ConversationTurnResponse(
                trace_id=t.trace_id,
                start_time=t.start_time,
                question=t.question,
                answer=t.answer,
                user_id=t.user_id,
                live_interaction_id=t.live_interaction_id,
                search_query=t.search_query,
            )
            for t in detail.turns
        ],
        scores=[_score(s) for s in detail.scores],
        live_interactions=[_live(i) for i in detail.live_interactions],
    )


@router.post("/{session_id}/score", response_model=ConversationDetailResponse)
async def score_conversation(
    project_id: uuid.UUID,
    session_id: str,
    use_case: ScoreConversation = Depends(get_score_conversation),
) -> ConversationDetailResponse:
    try:
        detail = await use_case.execute(project_id, session_id)
    except ProjectNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ConversationNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ConversationDetailResponse(
        summary=_summary(detail.summary),
        judge_status=detail.conversation.judge_status if detail.conversation else None,
        turns=[
            ConversationTurnResponse(
                trace_id=t.trace_id,
                start_time=t.start_time,
                question=t.question,
                answer=t.answer,
                user_id=t.user_id,
                live_interaction_id=t.live_interaction_id,
                search_query=t.search_query,
            )
            for t in detail.turns
        ],
        scores=[_score(s) for s in detail.scores],
        live_interactions=[_live(i) for i in detail.live_interactions],
    )


@router.post(
    "/{session_id}/promote",
    response_model=DatasetItemResponse,
    status_code=status.HTTP_201_CREATED,
)
async def promote_conversation(
    project_id: uuid.UUID,
    session_id: str,
    body: PromoteConversationRequest,
    use_case: PromoteConversation = Depends(get_promote_conversation),
) -> DatasetItemResponse:
    try:
        item = await use_case.execute(
            PromoteConversationCommand(
                project_id=project_id,
                session_id=session_id,
                dataset_id=body.dataset_id,
                expected_output=body.expected_output,
                expected_doc_ids=body.expected_doc_ids,
                mode=body.mode,
            )
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ConversationNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DatasetNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return DatasetItemResponse.model_validate(
        {
            "id": item.id,
            "dataset_id": item.dataset_id,
            "input": dump_dataset_input(item.input),
            "expected_output": item.expected_output,
            "actual_output": item.actual_output,
            "context": dump_context(item.context),
            "metadata": dump_metadata(item.metadata, exclude_none=True),
            "source_trace_id": item.source_trace_id,
            "source_span_id": item.source_span_id,
        }
    )
