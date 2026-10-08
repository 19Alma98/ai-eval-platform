from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.exc import IntegrityError

from aiobs.api.deps import (
    get_add_dataset_item,
    get_create_dataset,
    get_get_dataset,
    get_import_dataset_items,
    get_list_datasets,
)
from aiobs.api.schemas import (
    CreateDatasetItemRequest,
    CreateDatasetRequest,
    DatasetDetailResponse,
    DatasetItemResponse,
    DatasetResponse,
    ImportDatasetItemErrorResponse,
    ImportDatasetItemsResponse,
    TaskTypeResponse,
)
from aiobs.application.datasets import (
    AddDatasetItem,
    AddDatasetItemCommand,
    CreateDataset,
    CreateDatasetCommand,
    DatasetConflictError,
    DatasetNotFoundError,
    GetDataset,
    ImportDatasetItems,
    ImportDatasetItemsCommand,
    ImportDatasetTaskTypeError,
    ListDatasets,
)
from aiobs.application.projects import ProjectNotFoundError
from aiobs.domain.dataset import Dataset, DatasetItem
from aiobs.domain.task_types import TASK_TYPE_CATALOG, normalize_task_type

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


def _dataset_response(dataset: Dataset) -> DatasetResponse:
    return DatasetResponse(
        id=dataset.id,
        project_id=dataset.project_id,
        name=dataset.name,
        version=dataset.version,
        description=dataset.description,
        task_type=dataset.task_type,
        created_at=dataset.created_at,
    )


@router.get("/api/v1/task-types", response_model=list[TaskTypeResponse])
async def list_task_types() -> list[TaskTypeResponse]:
    return [
        TaskTypeResponse(
            id=info.id,
            label=info.label,
            field_hints=list(info.field_hints),
            recommended_evaluator_kinds=list(info.recommended_evaluator_kinds),
        )
        for info in TASK_TYPE_CATALOG
    ]


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
                task_type=body.task_type,
            )
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (DatasetConflictError, IntegrityError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _dataset_response(dataset)


@router.get(
    "/api/v1/projects/{project_id}/datasets",
    response_model=list[DatasetResponse],
)
async def list_datasets(
    project_id: uuid.UUID,
    task_type: str | None = Query(default=None),
    use_case: ListDatasets = Depends(get_list_datasets),
) -> list[DatasetResponse]:
    try:
        normalized = normalize_task_type(task_type)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    datasets = await use_case.execute(project_id, task_type=normalized)
    return [_dataset_response(d) for d in datasets]


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
        task_type=dataset.task_type,
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
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    return _item_response(item)


@router.post(
    "/api/v1/datasets/{dataset_id}/items/import",
    response_model=ImportDatasetItemsResponse,
)
async def import_dataset_items(
    dataset_id: uuid.UUID,
    file: UploadFile = File(...),
    format: str | None = Query(default=None),
    use_case: ImportDatasetItems = Depends(get_import_dataset_items),
) -> ImportDatasetItemsResponse:
    try:
        raw = await file.read()
        result = await use_case.execute(
            ImportDatasetItemsCommand(
                dataset_id=dataset_id,
                raw=raw,
                filename=file.filename,
                format=format,
            )
        )
    except DatasetNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ImportDatasetTaskTypeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    return ImportDatasetItemsResponse(
        created=result.created,
        errors=[
            ImportDatasetItemErrorResponse(row=e.row, message=e.message) for e in result.errors
        ],
    )
