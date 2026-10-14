from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status

from aiobs_server.api.deps import (
    get_create_metrics_set,
    get_delete_metrics_set,
    get_delete_metrics_set_entry,
    get_get_metrics_set,
    get_list_metrics_sets,
    get_patch_metrics_set,
    get_version_metrics_set,
)
from aiobs_server.api.schemas import (
    CreateMetricsSetRequest,
    MetricsSetEntryResponse,
    MetricsSetResponse,
    MetricsSetSummaryResponse,
    PatchMetricsSetRequest,
    VersionMetricsSetRequest,
)
from aiobs_server.application.metrics_sets import (
    CreateMetricsSet,
    CreateMetricsSetCommand,
    DeleteMetricsSet,
    DeleteMetricsSetEntry,
    GetMetricsSet,
    ListMetricsSets,
    MetricsSetConflictError,
    MetricsSetEntryInput,
    MetricsSetEntryNotFoundError,
    MetricsSetNotFoundError,
    MetricsSetProtectedError,
    MetricsSetReferencedError,
    MetricsSetValidationError,
    PatchMetricsSet,
    PatchMetricsSetCommand,
    VersionMetricsSet,
    VersionMetricsSetCommand,
)
from aiobs_server.application.projects import ProjectNotFoundError
from aiobs_server.domain.metrics_set import MetricsSet, MetricsSetEntry

router = APIRouter(tags=["metrics-sets"])


def _entry_response(entry: MetricsSetEntry) -> MetricsSetEntryResponse:
    return MetricsSetEntryResponse(
        id=entry.id,
        kind=entry.kind,
        enabled=entry.enabled,
        threshold=entry.threshold,
        config=dict(entry.config),
        evaluator_id=entry.evaluator_id,
        is_default=entry.is_default,
        created_at=entry.created_at,
    )


def _summary_response(metrics_set: MetricsSet) -> MetricsSetSummaryResponse:
    return MetricsSetSummaryResponse(
        id=metrics_set.id,
        project_id=metrics_set.project_id,
        name=metrics_set.name,
        version=metrics_set.version,
        description=metrics_set.description,
        is_project_default=metrics_set.is_project_default,
        created_at=metrics_set.created_at,
        updated_at=metrics_set.updated_at,
        entry_count=len(metrics_set.entries),
        enabled_count=sum(1 for e in metrics_set.entries if e.enabled),
    )


def _metrics_set_response(metrics_set: MetricsSet) -> MetricsSetResponse:
    summary = _summary_response(metrics_set)
    return MetricsSetResponse(
        **summary.model_dump(),
        entries=[_entry_response(e) for e in metrics_set.entries],
    )


def _entry_inputs_from_request(
    entries: list[Any],
) -> list[MetricsSetEntryInput]:
    return [
        MetricsSetEntryInput(
            kind=entry.kind,
            enabled=entry.enabled,
            threshold=entry.threshold,
            config=dict(entry.config),
            evaluator_id=entry.evaluator_id,
        )
        for entry in entries
    ]


def _http_conflict(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.get(
    "/api/v1/projects/{project_id}/metrics-sets",
    response_model=list[MetricsSetSummaryResponse],
)
async def list_metrics_sets(
    project_id: uuid.UUID,
    use_case: ListMetricsSets = Depends(get_list_metrics_sets),
) -> list[MetricsSetSummaryResponse]:
    try:
        sets = await use_case.execute(project_id)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return [_summary_response(s) for s in sets]


@router.post(
    "/api/v1/projects/{project_id}/metrics-sets",
    response_model=MetricsSetResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_metrics_set(
    project_id: uuid.UUID,
    body: CreateMetricsSetRequest,
    use_case: CreateMetricsSet = Depends(get_create_metrics_set),
) -> MetricsSetResponse:
    try:
        metrics_set = await use_case.execute(
            CreateMetricsSetCommand(
                project_id=project_id,
                name=body.name,
                description=body.description,
                entries=_entry_inputs_from_request(body.entries),
            )
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except MetricsSetConflictError as exc:
        raise _http_conflict(exc) from exc
    except MetricsSetValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _metrics_set_response(metrics_set)


@router.get(
    "/api/v1/metrics-sets/{metrics_set_id}",
    response_model=MetricsSetResponse,
)
async def get_metrics_set(
    metrics_set_id: uuid.UUID,
    use_case: GetMetricsSet = Depends(get_get_metrics_set),
) -> MetricsSetResponse:
    try:
        metrics_set = await use_case.execute(metrics_set_id)
    except MetricsSetNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _metrics_set_response(metrics_set)


@router.patch(
    "/api/v1/metrics-sets/{metrics_set_id}",
    response_model=MetricsSetResponse,
)
async def patch_metrics_set(
    metrics_set_id: uuid.UUID,
    body: PatchMetricsSetRequest,
    use_case: PatchMetricsSet = Depends(get_patch_metrics_set),
) -> MetricsSetResponse:
    patch_cmd: dict[str, Any] = {
        "metrics_set_id": metrics_set_id,
        "name": body.name,
        "entries": (_entry_inputs_from_request(body.entries) if body.entries is not None else None),
    }
    if "description" in body.model_fields_set:
        patch_cmd["description"] = body.description
    try:
        metrics_set = await use_case.execute(PatchMetricsSetCommand(**patch_cmd))
    except MetricsSetNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except MetricsSetReferencedError as exc:
        raise _http_conflict(exc) from exc
    except MetricsSetProtectedError as exc:
        raise _http_conflict(exc) from exc
    except MetricsSetConflictError as exc:
        raise _http_conflict(exc) from exc
    except MetricsSetValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _metrics_set_response(metrics_set)


@router.post(
    "/api/v1/metrics-sets/{metrics_set_id}/version",
    response_model=MetricsSetResponse,
    status_code=status.HTTP_201_CREATED,
)
async def version_metrics_set(
    metrics_set_id: uuid.UUID,
    body: VersionMetricsSetRequest,
    use_case: VersionMetricsSet = Depends(get_version_metrics_set),
) -> MetricsSetResponse:
    version_cmd: dict[str, Any] = {"metrics_set_id": metrics_set_id}
    if "description" in body.model_fields_set:
        version_cmd["description"] = body.description
    if body.entries is not None:
        version_cmd["entries"] = _entry_inputs_from_request(body.entries)
    try:
        metrics_set = await use_case.execute(VersionMetricsSetCommand(**version_cmd))
    except MetricsSetNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except MetricsSetConflictError as exc:
        raise _http_conflict(exc) from exc
    except MetricsSetValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _metrics_set_response(metrics_set)


@router.delete(
    "/api/v1/metrics-sets/{metrics_set_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_metrics_set(
    metrics_set_id: uuid.UUID,
    use_case: DeleteMetricsSet = Depends(get_delete_metrics_set),
) -> Response:
    try:
        await use_case.execute(metrics_set_id)
    except MetricsSetNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except MetricsSetReferencedError as exc:
        raise _http_conflict(exc) from exc
    except MetricsSetProtectedError as exc:
        raise _http_conflict(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/api/v1/metrics-sets/{metrics_set_id}/entries/{entry_id}",
    response_model=MetricsSetResponse,
)
async def delete_metrics_set_entry(
    metrics_set_id: uuid.UUID,
    entry_id: uuid.UUID,
    use_case: DeleteMetricsSetEntry = Depends(get_delete_metrics_set_entry),
) -> MetricsSetResponse:
    try:
        metrics_set = await use_case.execute(metrics_set_id, entry_id)
    except MetricsSetNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except MetricsSetEntryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except MetricsSetReferencedError as exc:
        raise _http_conflict(exc) from exc
    except MetricsSetProtectedError as exc:
        raise _http_conflict(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _metrics_set_response(metrics_set)
