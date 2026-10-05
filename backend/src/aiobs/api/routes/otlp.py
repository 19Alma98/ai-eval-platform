from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Header, Request, Response, status
from fastapi.responses import JSONResponse
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceResponse,
)

from aiobs.api.deps import (
    get_app_settings,
    get_bind_otlp_traces,
    get_ingest_traces,
    get_resolve_project,
)
from aiobs.application.traces import IngestNormalizedTraces, ProjectMissingError, ResolveProject
from aiobs.config import Settings
from aiobs.tracing.ingestion import ingest_otlp_payload
from aiobs.tracing.otel import OtlpDecodeError
from aiobs.tracing.run_binding import BindOtlpTracesToExperimentOutputs

logger = logging.getLogger(__name__)

router = APIRouter(tags=["otlp"])


@router.post("/v1/traces")
async def export_traces(
    request: Request,
    resolve: ResolveProject = Depends(get_resolve_project),
    ingest: IngestNormalizedTraces = Depends(get_ingest_traces),
    bind_outputs: BindOtlpTracesToExperimentOutputs = Depends(get_bind_otlp_traces),
    settings: Settings = Depends(get_app_settings),
    x_project_id: str | None = Header(default=None, alias="X-Project-Id"),
    x_project_slug: str | None = Header(default=None, alias="X-Project-Slug"),
) -> Response:
    body = await request.body()
    if len(body) > settings.otlp_max_body_bytes:
        return JSONResponse(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            content={"detail": "OTLP payload too large"},
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
        )
    except OtlpDecodeError as exc:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": str(exc)},
        )

    saved = await ingest.execute(traces)
    try:
        await bind_outputs.execute(saved)
    except Exception:
        logger.warning("OTLP experiment output binding failed", exc_info=True)

    # OTLP success: empty ExportTraceServiceResponse (protobuf bytes)
    response = ExportTraceServiceResponse()
    return Response(
        content=response.SerializeToString(),
        media_type="application/x-protobuf",
        status_code=status.HTTP_200_OK,
    )
