from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from opengrade_server.application.dataset_import import parse_import_payload, row_to_item_fields
from opengrade_server.application.metrics_packs import EnsureMetricsPack
from opengrade_server.application.projects import ProjectNotFoundError
from opengrade_server.domain.dataset import Dataset, DatasetItem
from opengrade_server.domain.rag_qa import validate_rag_qa_item
from opengrade_server.domain.repositories import (
    DatasetRepository,
    EvaluationRunRepository,
    ExperimentRepository,
    ProjectRepository,
)


class DatasetNotFoundError(Exception):
    def __init__(self, dataset_id: uuid.UUID) -> None:
        self.dataset_id = dataset_id
        super().__init__(f"Dataset not found: {dataset_id}")


class DatasetConflictError(Exception):
    def __init__(self, name: str, version: int) -> None:
        self.name = name
        self.version = version
        super().__init__(f"Dataset already exists: {name} v{version}")


@dataclass(frozen=True, slots=True)
class CreateDatasetCommand:
    project_id: uuid.UUID
    name: str
    version: int = 1
    description: str | None = None
    task_type: str | None = None


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
class ImportDatasetItemError:
    row: int
    message: str


@dataclass(frozen=True, slots=True)
class ImportDatasetItemsResult:
    created: int
    errors: list[ImportDatasetItemError]
    dataset_id: uuid.UUID
    version: int
    forked_from_dataset_id: uuid.UUID | None


@dataclass(frozen=True, slots=True)
class ImportDatasetItemsCommand:
    dataset_id: uuid.UUID
    raw: bytes
    filename: str | None = None
    format: str | None = None


class ImportDatasetTaskTypeError(Exception):
    def __init__(self, task_type: str | None) -> None:
        self.task_type = task_type
        super().__init__(f"Import is only supported for rag_qa datasets (got {task_type!r})")


def _is_unique_violation(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "uq_datasets_project_name_version" in text or "unique" in text


async def dataset_has_evaluation_runs(
    experiments: ExperimentRepository,
    runs: EvaluationRunRepository,
    dataset: Dataset,
) -> bool:
    for experiment in await experiments.list_by_project(dataset.project_id):
        if experiment.dataset_id != dataset.id:
            continue
        if await runs.list_runs_by_experiment(experiment.id):
            return True
    return False


async def next_dataset_version(
    datasets: DatasetRepository,
    project_id: uuid.UUID,
    name: str,
) -> int:
    versions = [d.version for d in await datasets.list_by_project(project_id) if d.name == name]
    return (max(versions) if versions else 0) + 1


async def ensure_writable_dataset(
    datasets: DatasetRepository,
    experiments: ExperimentRepository,
    runs: EvaluationRunRepository,
    dataset_id: uuid.UUID,
) -> tuple[Dataset, uuid.UUID | None]:
    """Return a mutable dataset, forking to version+1 when evaluation runs exist."""
    dataset = await datasets.get_by_id(dataset_id)
    if dataset is None:
        raise DatasetNotFoundError(dataset_id)
    if not await dataset_has_evaluation_runs(experiments, runs, dataset):
        return dataset, None

    siblings = [
        d for d in await datasets.list_by_project(dataset.project_id) if d.name == dataset.name
    ]
    tip = max(siblings, key=lambda d: d.version)
    if tip.id != dataset.id and not await dataset_has_evaluation_runs(experiments, runs, tip):
        return tip, None

    source = tip
    source_items = await datasets.list_items(source.id)
    last_conflict: Exception | None = None
    for _ in range(3):
        next_version = await next_dataset_version(datasets, source.project_id, source.name)
        copy = Dataset.create(
            source.project_id,
            source.name,
            version=next_version,
            description=source.description,
            task_type=source.task_type,
        )
        try:
            created = await datasets.add(copy)
        except Exception as exc:
            if _is_unique_violation(exc):
                last_conflict = exc
                continue
            raise
        for item in source_items:
            await datasets.add_item(
                DatasetItem.create(
                    created.id,
                    item.input,
                    expected_output=item.expected_output,
                    actual_output=item.actual_output,
                    context=item.context,
                    metadata=dict(item.metadata),
                    source_trace_id=item.source_trace_id,
                    source_span_id=item.source_span_id,
                )
            )
        return created, source.id

    raise DatasetConflictError(source.name, source.version + 1) from last_conflict


class CreateDataset:
    def __init__(
        self,
        datasets: DatasetRepository,
        projects: ProjectRepository,
        ensure_metrics_pack: EnsureMetricsPack | None = None,
    ) -> None:
        self._datasets = datasets
        self._projects = projects
        self._ensure_metrics_pack = ensure_metrics_pack

    async def execute(self, command: CreateDatasetCommand) -> Dataset:
        project = await self._projects.get_by_id(command.project_id)
        if project is None:
            raise ProjectNotFoundError(command.project_id)
        dataset = Dataset.create(
            command.project_id,
            command.name,
            version=command.version,
            description=command.description,
            task_type=command.task_type,
        )
        try:
            created = await self._datasets.add(dataset)
        except Exception as exc:
            # Repository may raise IntegrityError; map in infra or re-raise as conflict
            if _is_unique_violation(exc):
                raise DatasetConflictError(dataset.name, dataset.version) from exc
            raise
        if created.task_type == "rag_qa" and self._ensure_metrics_pack is not None:
            await self._ensure_metrics_pack.execute(command.project_id)
        return created


class ListDatasets:
    def __init__(self, datasets: DatasetRepository) -> None:
        self._datasets = datasets

    async def execute(
        self,
        project_id: uuid.UUID,
        *,
        task_type: str | None = None,
    ) -> list[Dataset]:
        return await self._datasets.list_by_project(project_id, task_type=task_type)


class GetDataset:
    def __init__(
        self,
        datasets: DatasetRepository,
        experiments: ExperimentRepository,
        runs: EvaluationRunRepository,
    ) -> None:
        self._datasets = datasets
        self._experiments = experiments
        self._runs = runs

    async def execute(self, dataset_id: uuid.UUID) -> tuple[Dataset, list[DatasetItem], bool]:
        dataset = await self._datasets.get_by_id(dataset_id)
        if dataset is None:
            raise DatasetNotFoundError(dataset_id)
        items = await self._datasets.list_items(dataset_id)
        immutable = await dataset_has_evaluation_runs(self._experiments, self._runs, dataset)
        return dataset, items, immutable


class AddDatasetItem:
    def __init__(
        self,
        datasets: DatasetRepository,
        experiments: ExperimentRepository,
        runs: EvaluationRunRepository,
    ) -> None:
        self._datasets = datasets
        self._experiments = experiments
        self._runs = runs

    async def execute(self, command: AddDatasetItemCommand) -> DatasetItem:
        target, _ = await ensure_writable_dataset(
            self._datasets,
            self._experiments,
            self._runs,
            command.dataset_id,
        )
        return await self._add_item_to(target, command)

    async def _add_item_to(self, dataset: Dataset, command: AddDatasetItemCommand) -> DatasetItem:
        metadata = command.metadata
        if dataset.task_type == "rag_qa":
            metadata = validate_rag_qa_item(
                input=command.input,
                expected_output=command.expected_output,
                metadata=dict(command.metadata or {}),
            )
        item = DatasetItem.create(
            dataset.id,
            command.input,
            expected_output=command.expected_output,
            actual_output=command.actual_output,
            context=command.context,
            metadata=metadata,
            source_trace_id=command.source_trace_id,
            source_span_id=command.source_span_id,
        )
        return await self._datasets.add_item(item)


class ImportDatasetItems:
    def __init__(
        self,
        datasets: DatasetRepository,
        experiments: ExperimentRepository,
        runs: EvaluationRunRepository,
    ) -> None:
        self._datasets = datasets
        self._experiments = experiments
        self._runs = runs
        self._add_item = AddDatasetItem(datasets, experiments, runs)

    async def execute(self, command: ImportDatasetItemsCommand) -> ImportDatasetItemsResult:
        dataset = await self._datasets.get_by_id(command.dataset_id)
        if dataset is None:
            raise DatasetNotFoundError(command.dataset_id)
        if dataset.task_type != "rag_qa":
            raise ImportDatasetTaskTypeError(dataset.task_type)

        parsed = parse_import_payload(
            filename=command.filename,
            raw=command.raw,
            format=command.format,
        )
        created = 0
        errors: list[ImportDatasetItemError] = []
        target: Dataset | None = None
        forked_from: uuid.UUID | None = None

        for index, row in enumerate(parsed.rows):
            row_num = parsed.first_row_number + index
            if not isinstance(row, dict):
                errors.append(
                    ImportDatasetItemError(
                        row=row_num,
                        message="Each JSON import row must be an object",
                    )
                )
                continue
            try:
                question, answer, meta = row_to_item_fields(row)
                if target is None:
                    target, forked_from = await ensure_writable_dataset(
                        self._datasets,
                        self._experiments,
                        self._runs,
                        command.dataset_id,
                    )
                await self._add_item._add_item_to(
                    target,
                    AddDatasetItemCommand(
                        dataset_id=target.id,
                        input=question,
                        expected_output=answer,
                        metadata=meta,
                    ),
                )
                created += 1
            except ValueError as exc:
                errors.append(ImportDatasetItemError(row=row_num, message=str(exc)))

        result_dataset = target if target is not None else dataset
        return ImportDatasetItemsResult(
            created=created,
            errors=errors,
            dataset_id=result_dataset.id,
            version=result_dataset.version,
            forked_from_dataset_id=forked_from,
        )
