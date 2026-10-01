from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from aiobs.application.projects import ProjectNotFoundError
from aiobs.domain.dataset import Dataset, DatasetItem
from aiobs.domain.repositories import DatasetRepository, ProjectRepository, TraceRepository
from aiobs.evaluation.trace_context import build_eval_context_from_trace


class DatasetNotFoundError(Exception):
    def __init__(self, dataset_id: uuid.UUID) -> None:
        self.dataset_id = dataset_id
        super().__init__(f"Dataset not found: {dataset_id}")


class DatasetConflictError(Exception):
    def __init__(self, name: str, version: int) -> None:
        self.name = name
        self.version = version
        super().__init__(f"Dataset already exists: {name} v{version}")


class TraceNotFoundForDatasetError(Exception):
    def __init__(self, project_id: uuid.UUID, trace_id: str) -> None:
        self.project_id = project_id
        self.trace_id = trace_id
        super().__init__(f"Trace not found: {trace_id} in project {project_id}")


@dataclass(frozen=True, slots=True)
class CreateDatasetCommand:
    project_id: uuid.UUID
    name: str
    version: int = 1
    description: str | None = None


@dataclass(frozen=True, slots=True)
class AddDatasetItemCommand:
    dataset_id: uuid.UUID
    input: Any
    expected_output: Any | None = None
    actual_output: Any | None = None
    context: Any | None = None
    metadata: dict[str, Any] | None = None
    source_trace_id: str | None = None
    source_span_id: str | None = None


@dataclass(frozen=True, slots=True)
class AddDatasetItemFromTraceCommand:
    dataset_id: uuid.UUID
    trace_id: str
    expected_output: Any | None = None
    source_span_id: str | None = None
    metadata: dict[str, Any] | None = None


class CreateDataset:
    def __init__(
        self,
        datasets: DatasetRepository,
        projects: ProjectRepository,
    ) -> None:
        self._datasets = datasets
        self._projects = projects

    async def execute(self, command: CreateDatasetCommand) -> Dataset:
        project = await self._projects.get_by_id(command.project_id)
        if project is None:
            raise ProjectNotFoundError(command.project_id)
        dataset = Dataset.create(
            command.project_id,
            command.name,
            version=command.version,
            description=command.description,
        )
        try:
            return await self._datasets.add(dataset)
        except Exception as exc:
            # Repository may raise IntegrityError; map in infra or re-raise as conflict
            if (
                "uq_datasets_project_name_version" in str(exc).lower()
                or "unique" in str(exc).lower()
            ):
                raise DatasetConflictError(dataset.name, dataset.version) from exc
            raise


class ListDatasets:
    def __init__(self, datasets: DatasetRepository) -> None:
        self._datasets = datasets

    async def execute(self, project_id: uuid.UUID) -> list[Dataset]:
        return await self._datasets.list_by_project(project_id)


class GetDataset:
    def __init__(self, datasets: DatasetRepository) -> None:
        self._datasets = datasets

    async def execute(self, dataset_id: uuid.UUID) -> tuple[Dataset, list[DatasetItem]]:
        dataset = await self._datasets.get_by_id(dataset_id)
        if dataset is None:
            raise DatasetNotFoundError(dataset_id)
        items = await self._datasets.list_items(dataset_id)
        return dataset, items


class AddDatasetItem:
    def __init__(self, datasets: DatasetRepository) -> None:
        self._datasets = datasets

    async def execute(self, command: AddDatasetItemCommand) -> DatasetItem:
        dataset = await self._datasets.get_by_id(command.dataset_id)
        if dataset is None:
            raise DatasetNotFoundError(command.dataset_id)
        item = DatasetItem.create(
            command.dataset_id,
            command.input,
            expected_output=command.expected_output,
            actual_output=command.actual_output,
            context=command.context,
            metadata=command.metadata,
            source_trace_id=command.source_trace_id,
            source_span_id=command.source_span_id,
        )
        return await self._datasets.add_item(item)


class AddDatasetItemFromTrace:
    def __init__(
        self,
        datasets: DatasetRepository,
        traces: TraceRepository,
    ) -> None:
        self._datasets = datasets
        self._traces = traces

    async def execute(self, command: AddDatasetItemFromTraceCommand) -> DatasetItem:
        dataset = await self._datasets.get_by_id(command.dataset_id)
        if dataset is None:
            raise DatasetNotFoundError(command.dataset_id)
        trace = await self._traces.get_by_trace_id(dataset.project_id, command.trace_id)
        if trace is None:
            raise TraceNotFoundForDatasetError(dataset.project_id, command.trace_id)

        context = build_eval_context_from_trace(trace, source_span_id=command.source_span_id)
        item = DatasetItem.create(
            command.dataset_id,
            input=trace.input if trace.input is not None else {},
            expected_output=command.expected_output,
            actual_output=trace.output,
            context=context or None,
            metadata=command.metadata,
            source_trace_id=trace.trace_id,
            source_span_id=command.source_span_id,
        )
        return await self._datasets.add_item(item)
