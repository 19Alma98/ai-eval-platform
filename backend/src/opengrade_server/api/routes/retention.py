from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status

from opengrade_server.api.deps import get_purge_production_data, get_set_project_retention
from opengrade_server.api.schemas import (
    PurgeReportResponse,
    RetentionResponse,
    SetRetentionRequest,
)
from opengrade_server.application.projects import ProjectNotFoundError
from opengrade_server.application.retention import (
    PurgeProductionData,
    PurgeReport,
    RetentionValidationError,
    SetProjectRetention,
)
from opengrade_server.config import get_settings

router = APIRouter(prefix="/api/v1/projects", tags=["retention"])


def _report(report: PurgeReport) -> PurgeReportResponse:
    return PurgeReportResponse(
        retention_days=report.retention_days,
        cutoff=report.cutoff,
        dry_run=report.dry_run,
        traces=report.traces,
        traces_kept=report.traces_kept,
        live_interactions=report.rows.get("live_interactions", 0),
        trace_scores=report.rows.get("trace_scores", 0),
        alert_events=report.rows.get("alert_events", 0),
    )


async def _retention(project_id: uuid.UUID, purge: PurgeProductionData) -> RetentionResponse:
    try:
        preview = await purge.execute(project_id, dry_run=True)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return RetentionResponse(
        project_id=project_id,
        retention_days=preview.project_days,
        default_days=get_settings().retention_days,
        effective_days=preview.retention_days,
        pending=_report(preview),
    )


@router.get("/{project_id}/retention", response_model=RetentionResponse)
async def get_retention(
    project_id: uuid.UUID,
    purge: PurgeProductionData = Depends(get_purge_production_data),
) -> RetentionResponse:
    """The project's retention and what a purge would delete now."""
    return await _retention(project_id, purge)


@router.put("/{project_id}/retention", response_model=RetentionResponse)
async def set_retention(
    project_id: uuid.UUID,
    body: SetRetentionRequest,
    use_case: SetProjectRetention = Depends(get_set_project_retention),
    purge: PurgeProductionData = Depends(get_purge_production_data),
) -> RetentionResponse:
    """Days of production data to keep; null falls back to the server's RETENTION_DAYS."""
    try:
        await use_case.execute(project_id, body.retention_days)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RetentionValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return await _retention(project_id, purge)


@router.post("/{project_id}/retention/purge", response_model=PurgeReportResponse)
async def purge_now(
    project_id: uuid.UUID,
    dry_run: bool = Query(default=False),
    purge: PurgeProductionData = Depends(get_purge_production_data),
) -> PurgeReportResponse:
    """Delete production data older than the retention period now (the server also does it
    every RETENTION_INTERVAL_HOURS)."""
    try:
        return _report(await purge.execute(project_id, dry_run=dry_run))
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
