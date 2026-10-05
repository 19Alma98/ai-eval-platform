from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from aiobs.api.deps import (
    get_ensure_metrics_pack,
    get_get_metrics_pack,
    get_replace_metrics_pack,
)
from aiobs.api.schemas import (
    MetricsPackEntryResponse,
    MetricsPackResponse,
    ReplaceMetricsPackRequest,
)
from aiobs.application.metrics_packs import (
    EnsureMetricsPack,
    GetMetricsPack,
    MetricsPackEntryPatch,
    MetricsPackNotFoundError,
    MetricsPackValidationError,
    ReplaceMetricsPack,
)
from aiobs.application.projects import ProjectNotFoundError
from aiobs.domain.metrics_pack import MetricsPack

router = APIRouter(tags=["metrics-packs"])


def _pack_response(pack: MetricsPack) -> MetricsPackResponse:
    return MetricsPackResponse(
        id=pack.id,
        project_id=pack.project_id,
        entries=[
            MetricsPackEntryResponse(
                kind=e.kind,
                enabled=e.enabled,
                threshold=e.threshold,
                config=dict(e.config),
                evaluator_id=e.evaluator_id,
                removable=e.removable,
            )
            for e in pack.entries
        ],
        updated_at=pack.updated_at,
    )


def _patches_from_request(body: ReplaceMetricsPackRequest) -> list[MetricsPackEntryPatch]:
    return [
        MetricsPackEntryPatch(
            kind=entry.kind,
            enabled=entry.enabled,
            threshold=entry.threshold,
            config=dict(entry.config),
            evaluator_id=entry.evaluator_id,
            removable=entry.removable,
        )
        for entry in body.entries
    ]


@router.get(
    "/api/v1/projects/{project_id}/metrics-pack",
    response_model=MetricsPackResponse,
)
async def get_metrics_pack(
    project_id: uuid.UUID,
    use_case: GetMetricsPack = Depends(get_get_metrics_pack),
) -> MetricsPackResponse:
    try:
        pack = await use_case.execute(project_id)
    except MetricsPackNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _pack_response(pack)


@router.put(
    "/api/v1/projects/{project_id}/metrics-pack",
    response_model=MetricsPackResponse,
)
async def replace_metrics_pack(
    project_id: uuid.UUID,
    body: ReplaceMetricsPackRequest,
    use_case: ReplaceMetricsPack = Depends(get_replace_metrics_pack),
) -> MetricsPackResponse:
    try:
        pack = await use_case.execute(project_id, _patches_from_request(body))
    except MetricsPackNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except MetricsPackValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _pack_response(pack)


@router.post(
    "/api/v1/projects/{project_id}/metrics-pack/ensure",
    response_model=MetricsPackResponse,
)
async def ensure_metrics_pack(
    project_id: uuid.UUID,
    use_case: EnsureMetricsPack = Depends(get_ensure_metrics_pack),
) -> MetricsPackResponse:
    try:
        pack = await use_case.execute(project_id)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _pack_response(pack)
