from __future__ import annotations

import uuid
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from aiobs_server.api.deps import (
    get_app_settings,
    get_log_trace_scores,
    get_summarize_trace_scores,
)
from aiobs_server.api.schemas import (
    LogTraceScoresRequest,
    LogTraceScoresResponse,
    TraceScoreLabel,
    TraceScoreResponse,
    TraceScoreSource,
    TraceScoreSummaryResponse,
    TraceScoreSummaryRowResponse,
)
from aiobs_server.application.projects import ProjectNotFoundError
from aiobs_server.application.trace_scores import (
    LogTraceScores,
    SummarizeTraceScores,
    TraceScoreInput,
)
from aiobs_server.domain.trace_score import TraceScore


class BodyLimitedRoute(APIRoute):
    """Answer 413 before pydantic parses a body over ``trace_scores_max_body_bytes``."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            provider = request.app.dependency_overrides.get(get_app_settings, get_app_settings)
            limit = provider().trace_scores_max_body_bytes
            declared = request.headers.get("content-length", "")
            too_large = declared.isdigit() and int(declared) > limit
            if not too_large:
                too_large = len(await request.body()) > limit
            if too_large:
                return JSONResponse(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    content={"detail": "Trace score payload too large"},
                )
            return await original(request)

        return handler


router = APIRouter(
    prefix="/api/v1/projects/{project_id}/trace-scores",
    tags=["trace-scores"],
    route_class=BodyLimitedRoute,
)

DEFAULT_SUMMARY_WINDOW = timedelta(hours=24)


def trace_score_response(score: TraceScore) -> TraceScoreResponse:
    return TraceScoreResponse(
        id=score.id,
        trace_id=score.trace_id,
        name=score.name,
        value=score.value,
        label=cast(TraceScoreLabel | None, score.label),
        explanation=score.explanation,
        threshold=score.threshold,
        source=cast(TraceScoreSource, score.source),
        author=score.author,
        metadata=dict(score.metadata),
        created_at=score.created_at,
        updated_at=score.updated_at,
    )


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=LogTraceScoresResponse)
async def log_trace_scores(
    project_id: uuid.UUID,
    body: LogTraceScoresRequest,
    use_case: LogTraceScores = Depends(get_log_trace_scores),
) -> LogTraceScoresResponse:
    items = [
        TraceScoreInput(
            trace_id=s.trace_id,
            name=s.name,
            value=s.value,
            label=s.label,
            explanation=s.explanation,
            threshold=s.threshold,
            source=s.source,
            author=s.author,
            metadata=s.metadata,
        )
        for s in body.scores
    ]
    try:
        accepted = await use_case.execute(project_id, items)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    return LogTraceScoresResponse(accepted=accepted)


@router.get("/summary", response_model=TraceScoreSummaryResponse)
async def summarize_trace_scores(
    project_id: uuid.UUID,
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    use_case: SummarizeTraceScores = Depends(get_summarize_trace_scores),
) -> TraceScoreSummaryResponse:
    # Naive query values are read as UTC (comparing them with aware datetimes raises).
    if since is not None and since.tzinfo is None:
        since = since.replace(tzinfo=UTC)
    if until is not None and until.tzinfo is None:
        until = until.replace(tzinfo=UTC)
    end = until or datetime.now(UTC)
    start = since or end - DEFAULT_SUMMARY_WINDOW
    try:
        rows = await use_case.execute(project_id, since=start, until=end)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return TraceScoreSummaryResponse(
        since=start,
        until=end,
        rows=[
            TraceScoreSummaryRowResponse(
                name=r.name, source=r.source, count=r.count, mean=r.mean, pass_rate=r.pass_rate
            )
            for r in rows
        ],
    )
