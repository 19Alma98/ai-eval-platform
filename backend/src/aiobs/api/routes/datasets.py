from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError

from aiobs.api.deps import (
    get_add_dataset_item,
    get_add_dataset_item_from_trace,
    get_create_dataset,
    get_get_dataset,
    get_list_datasets,
)
from aiobs.api.schemas import (
    CreateDatasetItemFromTraceRequest,
    CreateDatasetItemRequest,
    CreateDatasetRequest,
    DatasetDetailResponse,
    DatasetItemResponse,
    DatasetResponse,
)
from aiobs.application.datasets import (
    AddDatasetItem,
    AddDatasetItemCommand,
    AddDatasetItemFromTrace,
    AddDatasetItemFromTraceCommand,
    CreateDataset,
    CreateDatasetCommand,
    DatasetConflictError,
    DatasetNotFoundError,
    GetDataset,
    ListDatasets,
    TraceNotFoundForDatasetError,
)
from aiobs.application.projects import ProjectNotFoundError
from aiobs.domain.dataset import DatasetItem

router = APIRouter(tags=["datasets"])


def _item_response(item: DatasetItem) -> DatasetItemResponse:
    return DatasetItemResponse(
        id=item.id,
        dataset_id=item.dataset_id,
        input=item.input,
        expected_output=item.expected_output,
        actual_output=item.actual_output,
        context=item.context,
        metadata=item.metadata,
        source_trace_id=item.source_trace_id,
        source_span_id=item.source_span_id,
    )


@router.post(
    "/api/v1/projects/{project_id}/datasets",
    response_model=DatasetResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_dataset(
    project_id: uuid.UUID,
    body: CreateDatasetRequest,
    use_case: CreateDataset = Depends(get_create_dataset),
) -> DatasetResponse:
    try:
        dataset = await use_case.execute(
            CreateDatasetCommand(
                project_id=project_id,
                name=body.name,
                version=body.version,
                description=body.description,
            )
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (DatasetConflictError, IntegrityError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return DatasetResponse(
        id=dataset.id,
        project_id=dataset.project_id,
        name=dataset.name,
        version=dataset.version,
        description=dataset.description,
        created_at=dataset.created_at,
    )


@router.get(
    "/api/v1/projects/{project_id}/datasets",
    response_model=list[DatasetResponse],
)
async def list_datasets(
    project_id: uuid.UUID,
    use_case: ListDatasets = Depends(get_list_datasets),
) -> list[DatasetResponse]:
    datasets = await use_case.execute(project_id)
    return [
        DatasetResponse(
            id=d.id,
            project_id=d.project_id,
            name=d.name,
            version=d.version,
            description=d.description,
            created_at=d.created_at,
        )
        for d in datasets
    ]


@router.get("/api/v1/datasets/{dataset_id}", response_model=DatasetDetailResponse)
async def get_dataset(
    dataset_id: uuid.UUID,
    use_case: GetDataset = Depends(get_get_dataset),
) -> DatasetDetailResponse:
    try:
        dataset, items = await use_case.execute(dataset_id)
    except DatasetNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return DatasetDetailResponse(
        id=dataset.id,
        project_id=dataset.project_id,
        name=dataset.name,
        version=dataset.version,
        description=dataset.description,
        created_at=dataset.created_at,
        items=[_item_response(i) for i in items],
    )


@router.post(
    "/api/v1/datasets/{dataset_id}/items",
    response_model=DatasetItemResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_dataset_item(
    dataset_id: uuid.UUID,
    body: CreateDatasetItemRequest,
    use_case: AddDatasetItem = Depends(get_add_dataset_item),
) -> DatasetItemResponse:
    try:
        item = await use_case.execute(
            AddDatasetItemCommand(
                dataset_id=dataset_id,
                input=body.input,
                expected_output=body.expected_output,
                actual_output=body.actual_output,
                context=body.context,
                metadata=body.metadata,
                source_trace_id=body.source_trace_id,
                source_span_id=body.source_span_id,
            )
        )
    except DatasetNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _item_response(item)


@router.post(
    "/api/v1/datasets/{dataset_id}/items/from-trace",
    response_model=DatasetItemResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_dataset_item_from_trace(
    dataset_id: uuid.UUID,
    body: CreateDatasetItemFromTraceRequest,
    use_case: AddDatasetItemFromTrace = Depends(get_add_dataset_item_from_trace),
) -> DatasetItemResponse:
    try:
        item = await use_case.execute(
            AddDatasetItemFromTraceCommand(
                dataset_id=dataset_id,
                trace_id=body.trace_id,
                expected_output=body.expected_output,
                source_span_id=body.source_span_id,
                metadata=body.metadata,
            )
        )
    except DatasetNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except TraceNotFoundForDatasetError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _item_response(item)
