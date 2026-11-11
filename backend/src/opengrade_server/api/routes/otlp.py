from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Header, Request, Response, status
from fastapi.responses import JSONResponse
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceResponse,
)

from opengrade_server.api.body_limit import BodyTooLarge, read_body_capped
from opengrade_server.api.deps import (
    get_app_settings,
    get_bind_otlp_traces,
    get_conversation_repository,
    get_create_live_from_traces,
    get_ingest_traces,
    get_resolve_project,
    get_trace_repository,
)
from opengrade_server.api.otlp_backpressure import OtlpRejected, get_otlp_backpressure
from opengrade_server.application.background_tasks import (
    enqueue_live_score,
    live_score_inflight,
)
from opengrade_server.application.conversations import refresh_conversation_from_trace
from opengrade_server.application.traces import (
    IngestNormalizedTraces,
    ProjectMissingError,
    ResolveProject,
)
from opengrade_server.config import Settings
from opengrade_server.infrastructure.conversation_repository import (
    SqlAlchemyConversationRepository,
)
from opengrade_server.infrastructure.repositories import SqlAlchemyTraceRepository
from opengrade_server.tracing.http_body import (
    BodyDecodeError,
    BodyTooLargeError,
    UnsupportedContentEncodingError,
    decompress_http_body,
)
from opengrade_server.tracing.ingestion import ingest_otlp_payload
from opengrade_server.tracing.live_binding import (
    CreateLiveInteractionsFromTraces,
    traces_for_live_binding,
)
from opengrade_server.tracing.otel import OtlpDecodeError
from opengrade_server.tracing.run_binding import (
    BindOtlpTracesToExperimentOutputs,
    is_experiment_bound,
    traces_for_output_binding,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["otlp"])


@router.post("/v1/traces")
async def export_traces(
    request: Request,
    resolve: ResolveProject = Depends(get_resolve_project),
    ingest: IngestNormalizedTraces = Depends(get_ingest_traces),
    bind_outputs: BindOtlpTracesToExperimentOutputs = Depends(get_bind_otlp_traces),
    create_live: CreateLiveInteractionsFromTraces = Depends(get_create_live_from_traces),
    conversations: SqlAlchemyConversationRepository = Depends(get_conversation_repository),
    traces_repo: SqlAlchemyTraceRepository = Depends(get_trace_repository),
    settings: Settings = Depends(get_app_settings),
    x_project_id: str | None = Header(default=None, alias="X-Project-Id"),
    x_project_slug: str | None = Header(default=None, alias="X-Project-Slug"),
) -> Response:
    gate = get_otlp_backpressure(settings)
    try:
        async with gate.slot(pending_scores=live_score_inflight()):
            try:
                wire = await read_body_capped(request, settings.otlp_max_body_bytes)
            except BodyTooLarge:
                return JSONResponse(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    content={"detail": "OTLP payload too large"},
                )

            try:
                body = decompress_http_body(
                    wire,
                    request.headers.get("content-encoding"),
                    max_bytes=settings.otlp_max_body_bytes,
                )
            except BodyTooLargeError:
                return JSONResponse(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    content={"detail": "OTLP payload too large"},
                )
            except UnsupportedContentEncodingError as exc:
                return JSONResponse(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    content={"detail": str(exc)},
                )
            except BodyDecodeError as exc:
                return JSONResponse(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    content={"detail": str(exc)},
                )

            try:
                project_id = await resolve.from_otlp_headers(
                    project_id=x_project_id,
                    project_slug=x_project_slug,
                )
            except ValueError as exc:
                return JSONResponse(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    content={"detail": str(exc)},
                )
            except ProjectMissingError as exc:
                return JSONResponse(
                    status_code=status.HTTP_404_NOT_FOUND,
                    content={"detail": str(exc)},
                )

            try:
                traces = ingest_otlp_payload(
                    project_id=project_id,
                    body=body,
                    content_type=request.headers.get("content-type"),
                    content_capture_enabled=settings.content_capture_enabled,
                    sample_rate=settings.otlp_trace_sample_rate,
                    max_span_attr_chars=settings.otlp_max_span_attr_chars,
                )
            except OtlpDecodeError as exc:
                return JSONResponse(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    content={"detail": str(exc)},
                )

            saved = await ingest.execute(traces)
            try:
                await bind_outputs.execute(traces_for_output_binding(traces, saved))
            except Exception:
                logger.warning("OTLP experiment output binding failed", exc_info=True)
            try:
                to_score = await create_live.execute(traces_for_live_binding(traces, saved))
            except Exception:
                logger.warning("OTLP live interaction binding failed", exc_info=True)
                to_score = []
            for interaction_id in to_score:
                enqueue_live_score(interaction_id)

            payload_by_id = {t.trace_id: t for t in traces}
            sessions = {
                (t.project_id, t.session_id)
                for t in saved
                if t.session_id and str(t.session_id).strip()
            }
            for project_id_ref, session_id in sessions:
                batch = [
                    payload_by_id.get(t.trace_id, t)
                    for t in saved
                    if t.project_id == project_id_ref and t.session_id == session_id
                ]
                if batch and all(is_experiment_bound(t) for t in batch):
                    continue
                try:
                    await refresh_conversation_from_trace(
                        conversations, traces_repo, project_id_ref, session_id
                    )
                except Exception:
                    logger.warning(
                        "OTLP conversation refresh failed for session %s",
                        session_id,
                        exc_info=True,
                    )

            response = ExportTraceServiceResponse()
            return Response(
                content=response.SerializeToString(),
                media_type="application/x-protobuf",
                status_code=status.HTTP_200_OK,
            )
    except OtlpRejected as exc:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers={"Retry-After": str(exc.retry_after)},
        )
