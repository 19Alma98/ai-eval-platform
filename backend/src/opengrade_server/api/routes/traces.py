from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from opengrade_server.api.deps import (
    get_get_trace,
    get_list_trace_scores,
    get_list_traces,
    get_resolve_trace_live_links,
    get_trace_facets,
)
from opengrade_server.api.routes.trace_scores import trace_score_response
from opengrade_server.api.schemas import (
    SpanResponse,
    TraceDetailResponse,
    TraceFacetsResponse,
    TraceFacetValueResponse,
    TraceListResponse,
    TraceSummaryResponse,
)
from opengrade_server.application.trace_scores import ListTraceScores
from opengrade_server.application.traces import (
    GetTrace,
    GetTraceFacets,
    InvalidTraceCursorError,
    InvalidTraceFilterError,
    ListTraces,
    ProjectMissingError,
    ResolveTraceLiveLinks,
    TraceNotFoundError,
    parse_metadata_filters,
)
from opengrade_server.domain.trace import Trace
from opengrade_server.domain.trace_score import TraceScore
from opengrade_server.tracing.live_binding import answer_from_output, question_from_input

router = APIRouter(prefix="/api/v1/projects/{project_id}/traces", tags=["traces"])

_PREVIEW_LEN = 200
_TRACE_STATUSES = {"ok", "error", "unset"}


def _preview(value: Any) -> str | None:
    if value is None:
        return None
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    text = " ".join(text.split())
    if not text:
        return None
    return text if len(text) <= _PREVIEW_LEN else text[: _PREVIEW_LEN - 1] + "…"


def _duration_ms(trace: Trace) -> float | None:
    if trace.end_time is None:
        return None
    return (trace.end_time - trace.start_time).total_seconds() * 1000.0


def _to_summary(
    trace: Trace, scores: list[TraceScore], live_interaction_id: uuid.UUID | None
) -> TraceSummaryResponse:
    span_count = trace.metadata.get("_span_count")
    return TraceSummaryResponse(
        id=trace.id,
        trace_id=trace.trace_id,
        name=trace.name,
        status=trace.status,
        start_time=trace.start_time,
        end_time=trace.end_time,
        duration_ms=_duration_ms(trace),
        span_count=span_count if isinstance(span_count, int) else len(trace.spans),
        environment=trace.environment,
        version=trace.version,
        user_id=trace.user_id,
        session_id=trace.session_id,
        tags=list(trace.tags),
        # `@opengrade.trace` records {"args", "kwargs"}: show the question, not the envelope.
        input_preview=_preview(question_from_input(trace.input) if trace.input else None),
        output_preview=_preview(answer_from_output(trace.output) if trace.output else None),
        scores=[trace_score_response(s) for s in scores],
        live_interaction_id=live_interaction_id,
    )


def _to_detail(
    trace: Trace, scores: list[TraceScore], live_interaction_id: uuid.UUID | None
) -> TraceDetailResponse:
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
        version=trace.version,
        user_id=trace.user_id,
        session_id=trace.session_id,
        tags=list(trace.tags),
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
        scores=[trace_score_response(s) for s in scores],
        live_interaction_id=live_interaction_id,
    )


@router.get("", response_model=TraceListResponse)
async def list_traces(
    project_id: uuid.UUID,
    status_filter: str | None = Query(default=None, alias="status"),
    search: str | None = Query(default=None, max_length=200),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    cursor: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    environment: str | None = Query(default=None, max_length=200),
    version: str | None = Query(default=None, max_length=200),
    user_id: str | None = Query(default=None, max_length=200),
    session_id: str | None = Query(default=None, max_length=200),
    tag: list[str] = Query(
        default_factory=list, max_length=20, description="Repeat for AND: every tag must match"
    ),
    metadata: list[str] = Query(
        default_factory=list,
        max_length=20,
        description="key:value on trace metadata; repeat for AND",
    ),
    use_case: ListTraces = Depends(get_list_traces),
) -> TraceListResponse:
    if status_filter is not None and status_filter not in _TRACE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"status must be one of: {', '.join(sorted(_TRACE_STATUSES))}",
        )
    try:
        metadata_pairs = parse_metadata_filters(metadata)
    except InvalidTraceFilterError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    try:
        page = await use_case.execute(
            project_id,
            status=status_filter,
            search=search,
            since=since,
            until=until,
            cursor=cursor,
            limit=limit,
            environment=environment,
            version=version,
            user_id=user_id or None,
            session_id=session_id or None,
            tags=[t.strip() for t in tag if t.strip()],
            metadata=metadata_pairs,
        )
    except ProjectMissingError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except InvalidTraceCursorError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return TraceListResponse(
        items=[
            _to_summary(
                trace,
                page.scores.get(trace.trace_id, []),
                page.live_interaction_ids.get(trace.trace_id),
            )
            for trace in page.traces
        ],
        next_cursor=page.next_cursor,
    )


@router.get("/facets", response_model=TraceFacetsResponse)
async def trace_facets(
    project_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),
    use_case: GetTraceFacets = Depends(get_trace_facets),
) -> TraceFacetsResponse:
    """Tags, metadata keys, users and sessions seen in the project, most used first."""
    try:
        facets = await use_case.execute(project_id, limit=limit)
    except ProjectMissingError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return TraceFacetsResponse(
        **{
            name: [TraceFacetValueResponse(value=v, count=n) for v, n in rows]
            for name, rows in facets.items()
        }
    )


@router.get("/{trace_id}", response_model=TraceDetailResponse)
async def get_trace(
    project_id: uuid.UUID,
    trace_id: str,
    use_case: GetTrace = Depends(get_get_trace),
    list_scores: ListTraceScores = Depends(get_list_trace_scores),
    live_links: ResolveTraceLiveLinks = Depends(get_resolve_trace_live_links),
) -> TraceDetailResponse:
    try:
        trace = await use_case.execute(project_id, trace_id)
    except ProjectMissingError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except TraceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    links = await live_links.execute(project_id, [trace.trace_id])
    return _to_detail(
        trace,
        await list_scores.execute(project_id, trace.trace_id),
        links.get(trace.trace_id),
    )
