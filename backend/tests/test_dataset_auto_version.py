from __future__ import annotations

import uuid

import pytest

from aiobs_server.application.datasets import (
    AddDatasetItem,
    AddDatasetItemCommand,
    ImportDatasetItems,
    ImportDatasetItemsCommand,
)
from aiobs_server.application.live_interactions import (
    PromoteLiveInteraction,
    PromoteLiveInteractionCommand,
)
from aiobs_server.domain.dataset import Dataset, DatasetItem
from aiobs_server.domain.evaluation import EvaluationRun
from aiobs_server.domain.experiment import Experiment
from aiobs_server.domain.live_interaction import LiveInteraction


class InMemoryDatasetRepository:
    def __init__(self) -> None:
        self._datasets: dict[uuid.UUID, Dataset] = {}
        self._items: dict[uuid.UUID, DatasetItem] = {}

    async def add(self, dataset: Dataset) -> Dataset:
        self._datasets[dataset.id] = dataset
        return dataset

    async def get_by_id(self, dataset_id: uuid.UUID) -> Dataset | None:
        return self._datasets.get(dataset_id)

    async def list_by_project(
        self,
        project_id: uuid.UUID,
        *,
        task_type: str | None = None,
    ) -> list[Dataset]:
        return [
            d
            for d in self._datasets.values()
            if d.project_id == project_id and (task_type is None or d.task_type == task_type)
        ]

    async def add_item(self, item: DatasetItem) -> DatasetItem:
        self._items[item.id] = item
        return item

    async def list_items(self, dataset_id: uuid.UUID) -> list[DatasetItem]:
        return [i for i in self._items.values() if i.dataset_id == dataset_id]

    async def get_item(self, item_id: uuid.UUID) -> DatasetItem | None:
        return self._items.get(item_id)


class InMemoryExperimentRepository:
    def __init__(self) -> None:
        self._items: dict[uuid.UUID, Experiment] = {}

    async def add(self, experiment: Experiment) -> Experiment:
        self._items[experiment.id] = experiment
        return experiment

    async def get_by_id(self, experiment_id: uuid.UUID) -> Experiment | None:
        return self._items.get(experiment_id)

    async def list_by_project(self, project_id: uuid.UUID) -> list[Experiment]:
        return [e for e in self._items.values() if e.project_id == project_id]

    async def list_by_status(self, status: str, *, limit: int = 500) -> list[Experiment]:
        return [e for e in self._items.values() if e.status == status][:limit]

    async def update(self, experiment: Experiment) -> Experiment:
        self._items[experiment.id] = experiment
        return experiment

    async def count_by_metrics_set_id(self, metrics_set_id: uuid.UUID) -> int:
        return sum(1 for e in self._items.values() if e.metrics_set_id == metrics_set_id)


class InMemoryEvaluationRunRepository:
    def __init__(self) -> None:
        self._runs: dict[uuid.UUID, EvaluationRun] = {}

    async def add_run(self, run: EvaluationRun) -> EvaluationRun:
        self._runs[run.id] = run
        return run

    async def update_run(self, run: EvaluationRun) -> EvaluationRun:
        self._runs[run.id] = run
        return run

    async def get_run(self, run_id: uuid.UUID) -> EvaluationRun | None:
        return self._runs.get(run_id)

    async def list_runs_by_experiment(self, experiment_id: uuid.UUID) -> list[EvaluationRun]:
        return [r for r in self._runs.values() if r.experiment_id == experiment_id]

    async def add_result(self, result):  # noqa: ANN001
        return result

    async def list_results(self, run_id: uuid.UUID) -> list:
        return []

    async def add_results(self, results: list) -> list:
        return results


async def _seed_dataset_with_item(
    datasets: InMemoryDatasetRepository,
) -> tuple[Dataset, DatasetItem]:
    project_id = uuid.uuid4()
    dataset = Dataset.create(project_id, "gold", version=1, task_type="rag_qa")
    await datasets.add(dataset)
    item = DatasetItem.create(
        dataset.id,
        "Q1?",
        expected_output="A1",
        metadata={"expected_doc_ids": ["doc-1"]},
    )
    await datasets.add_item(item)
    return dataset, item


@pytest.mark.asyncio
async def test_add_item_without_runs_keeps_same_dataset() -> None:
    datasets = InMemoryDatasetRepository()
    experiments = InMemoryExperimentRepository()
    runs = InMemoryEvaluationRunRepository()
    dataset, _ = await _seed_dataset_with_item(datasets)

    uc = AddDatasetItem(datasets, experiments, runs)
    created = await uc.execute(
        AddDatasetItemCommand(
            dataset_id=dataset.id,
            input="Q2?",
            expected_output="A2",
            metadata={"expected_doc_ids": ["doc-2"]},
        )
    )

    assert created.dataset_id == dataset.id
    assert len(await datasets.list_items(dataset.id)) == 2


@pytest.mark.asyncio
async def test_add_item_after_run_forks_new_version() -> None:
    datasets = InMemoryDatasetRepository()
    experiments = InMemoryExperimentRepository()
    runs = InMemoryEvaluationRunRepository()
    dataset, original_item = await _seed_dataset_with_item(datasets)

    experiment = Experiment.create(dataset.project_id, "exp", dataset.id)
    await experiments.add(experiment)
    await runs.add_run(EvaluationRun.create(experiment.id, uuid.uuid4(), status="PASSED"))

    uc = AddDatasetItem(datasets, experiments, runs)
    created = await uc.execute(
        AddDatasetItemCommand(
            dataset_id=dataset.id,
            input="Q2?",
            expected_output="A2",
            metadata={"expected_doc_ids": ["doc-2"]},
        )
    )

    assert created.dataset_id != dataset.id
    forked = await datasets.get_by_id(created.dataset_id)
    assert forked is not None
    assert forked.name == dataset.name
    assert forked.version == 2

    old_items = await datasets.list_items(dataset.id)
    assert len(old_items) == 1
    assert old_items[0].id == original_item.id

    new_items = await datasets.list_items(forked.id)
    assert len(new_items) == 2
    assert {i.input for i in new_items} == {"Q1?", "Q2?"}
    assert all(i.id != original_item.id for i in new_items if i.input == "Q1?")


@pytest.mark.asyncio
async def test_import_on_frozen_dataset_forks_once() -> None:
    datasets = InMemoryDatasetRepository()
    experiments = InMemoryExperimentRepository()
    runs = InMemoryEvaluationRunRepository()
    dataset, _ = await _seed_dataset_with_item(datasets)

    experiment = Experiment.create(dataset.project_id, "exp", dataset.id)
    await experiments.add(experiment)
    await runs.add_run(EvaluationRun.create(experiment.id, uuid.uuid4(), status="RUNNING"))

    csv_body = (
        "question,expected_answer,expected_doc_ids\n"
        "What is X?,Answer X,doc-x\n"
        "What is Y?,Answer Y,doc-y\n"
    ).encode()

    uc = ImportDatasetItems(datasets, experiments, runs)
    result = await uc.execute(
        ImportDatasetItemsCommand(
            dataset_id=dataset.id,
            raw=csv_body,
            filename="items.csv",
        )
    )

    assert result.created == 2
    assert result.errors == []
    assert result.forked_from_dataset_id == dataset.id
    assert result.dataset_id != dataset.id
    assert result.version == 2

    assert len(await datasets.list_items(dataset.id)) == 1
    assert len(await datasets.list_items(result.dataset_id)) == 3

    versions = {d.version for d in await datasets.list_by_project(dataset.project_id)}
    assert versions == {1, 2}


class _LiveStub:
    def __init__(self, interaction: LiveInteraction) -> None:
        self._interaction = interaction

    async def get_by_id(self, interaction_id: uuid.UUID) -> LiveInteraction | None:
        if interaction_id == self._interaction.id:
            return self._interaction
        return None


@pytest.mark.asyncio
async def test_promote_on_frozen_dataset_forks_once() -> None:
    datasets = InMemoryDatasetRepository()
    experiments = InMemoryExperimentRepository()
    runs = InMemoryEvaluationRunRepository()
    dataset, _ = await _seed_dataset_with_item(datasets)

    experiment = Experiment.create(dataset.project_id, "exp", dataset.id)
    await experiments.add(experiment)
    await runs.add_run(EvaluationRun.create(experiment.id, uuid.uuid4(), status="PASSED"))

    interaction = LiveInteraction.create(
        dataset.project_id,
        "Promoted Q?",
        "Promoted A",
        documents=[{"id": "doc-p", "text": "ctx"}],
    )
    add_item = AddDatasetItem(datasets, experiments, runs)
    promote = PromoteLiveInteraction(_LiveStub(interaction), datasets, add_item)
    item = await promote.execute(
        PromoteLiveInteractionCommand(
            interaction_id=interaction.id,
            dataset_id=dataset.id,
            expected_output="Gold answer",
            expected_doc_ids=["doc-p"],
        )
    )

    assert item.dataset_id != dataset.id
    forked = await datasets.get_by_id(item.dataset_id)
    assert forked is not None
    assert forked.version == 2
    assert len(await datasets.list_items(dataset.id)) == 1
    assert len(await datasets.list_items(forked.id)) == 2
