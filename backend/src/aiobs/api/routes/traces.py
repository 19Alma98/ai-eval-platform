from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status

from aiobs.api.deps import (
    get_create_trace,
    get_get_trace,
    get_list_traces,
    get_project_repository,
)
from aiobs.api.schemas import (
    CreateTraceRequest,
    SpanResponse,
    TraceDetailResponse,
    TraceListResponse,
    TraceSummaryResponse,
)
from aiobs.application.traces import (
    CreateTrace,
    GetTrace,
    ListTraces,
    ListTracesQuery,
    ProjectMissingError,
    TraceNotFoundError,
)
from aiobs.config import get_settings
from aiobs.domain.trace import Span, Trace
from aiobs.infrastructure.repositories import SqlAlchemyProjectRepository
from aiobs.tracing.redaction import redact_trace

router = APIRouter(prefix="/api/v1/projects/{project_id}/traces", tags=["traces"])


def _to_detail(trace: Trace) -> TraceDetailResponse:
    return TraceDetailResponse(
        id=trace.id,
        project_id=trace.project_id,
        trace_id=trace.trace_id,
        name=trace.name,
        status=trace.status,
        start_time=trace.start_time,
        end_time=trace.end_time,
        input=trace.input,
        output=trace.output,
        metadata=dict(trace.metadata),
        environment=trace.environment,
        user_id=trace.user_id,
        session_id=trace.session_id,
        spans=[
            SpanResponse(
                span_id=span.span_id,
                parent_span_id=span.parent_span_id,
                name=span.name,
                kind=span.kind,
                start_time=span.start_time,
                end_time=span.end_time,
                status=span.status,
                attributes=dict(span.attributes),
                events=list(span.events),
            )
            for span in trace.spans
        ],
    )


@router.get("", response_model=TraceListResponse)
async def list_traces(
    project_id: uuid.UUID,
    status_filter: str | None = Query(default=None, alias="status"),
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    use_case: ListTraces = Depends(get_list_traces),
    projects: SqlAlchemyProjectRepository = Depends(get_project_repository),
) -> TraceListResponse:
    project = await projects.get_by_id(project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    result = await use_case.execute(
        ListTracesQuery(
            project_id=project_id,
            status=status_filter,
            start_time=start,
            end_time=end,
            cursor=cursor,
            limit=limit,
        )
    )
    return TraceListResponse(
        items=[
            TraceSummaryResponse(
                trace_id=trace.trace_id,
                name=trace.name,
                status=trace.status,
                start_time=trace.start_time,
                end_time=trace.end_time,
                span_count=result.span_counts.get(trace.id, 0),
            )
            for trace in result.items
        ],
        next_cursor=result.next_cursor,
    )


@router.get("/{trace_id}", response_model=TraceDetailResponse)
async def get_trace(
    project_id: uuid.UUID,
    trace_id: str,
    use_case: GetTrace = Depends(get_get_trace),
) -> TraceDetailResponse:
    try:
        trace = await use_case.execute(project_id, trace_id)
    except ProjectMissingError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except TraceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _to_detail(trace)


@router.post("", response_model=TraceDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_trace(
    project_id: uuid.UUID,
    body: CreateTraceRequest,
    use_case: CreateTrace = Depends(get_create_trace),
    projects: SqlAlchemyProjectRepository = Depends(get_project_repository),
) -> TraceDetailResponse:
    project = await projects.get_by_id(project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    settings = get_settings()
    spans = tuple(
        Span(
            id=uuid.uuid4(),
            span_id=span.span_id,
            parent_span_id=span.parent_span_id,
            name=span.name,
            kind=span.kind,
            start_time=span.start_time,
            end_time=span.end_time,
            status=span.status,
            attributes=dict(span.attributes),
            events=list(span.events),
        )
        for span in body.spans
    )
    trace = Trace(
        id=uuid.uuid4(),
        project_id=project_id,
        trace_id=body.trace_id.lower(),
        name=body.name,
        status=body.status,
        start_time=body.start_time,
        end_time=body.end_time,
        input=body.input,
        output=body.output,
        metadata=dict(body.metadata),
        environment=body.environment,
        user_id=body.user_id,
        session_id=body.session_id,
        spans=spans,
    )
    redacted = redact_trace(trace, content_capture_enabled=settings.content_capture_enabled)
    saved = await use_case.execute(redacted)
    return _to_detail(saved)
