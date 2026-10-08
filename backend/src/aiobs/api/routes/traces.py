from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from aiobs.api.deps import get_get_trace
from aiobs.api.schemas import SpanResponse, TraceDetailResponse
from aiobs.application.traces import GetTrace, ProjectMissingError, TraceNotFoundError
from aiobs.domain.trace import Trace

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
