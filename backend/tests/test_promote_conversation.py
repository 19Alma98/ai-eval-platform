from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from opengrade_server.application.conversations import (
    ConversationDetail,
    ConversationSummary,
    ConversationTurn,
    PromoteConversation,
    PromoteConversationCommand,
)
from opengrade_server.application.datasets import AddDatasetItem
from opengrade_server.domain.dataset import Dataset, DatasetItem
from opengrade_server.domain.evaluation import EvaluationRun
from opengrade_server.domain.experiment import Experiment
from opengrade_server.domain.rag_models import RagChatInput


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
        **kwargs: object,
    ) -> list[Dataset]:
        return [
            d
            for d in self._datasets.values()
            if d.project_id == project_id and (task_type is None or d.task_type == task_type)
        ]

    async def add_item(self, item: DatasetItem) -> DatasetItem:
        self._items[item.id] = item
        return item

    async def count_items(self, dataset_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
        return {d: len(await self.list_items(d)) for d in dataset_ids}

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

    async def list_by_project(self, project_id: uuid.UUID, **kwargs: object) -> list[Experiment]:
        return [e for e in self._items.values() if e.project_id == project_id]

    async def list_by_status(self, status: str, *, limit: int = 500) -> list[Experiment]:
        return [e for e in self._items.values() if e.status == status][:limit]

    async def update(self, experiment: Experiment) -> Experiment:
        self._items[experiment.id] = experiment
        return experiment

    async def try_mark_running(self, experiment_id: uuid.UUID) -> Experiment | None:
        exp = self._items.get(experiment_id)
        if exp is None or exp.status == "running":
            return None
        updated = exp.with_status("running")
        self._items[experiment_id] = updated
        return updated

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

    async def add_result(self, result: Any) -> Any:
        return result

    async def list_results(self, run_id: uuid.UUID) -> list:
        return []

    async def add_results(self, results: list) -> list:
        return results

    async def count_by_experiment_ids(
        self, experiment_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, int]:
        return {eid: 0 for eid in experiment_ids}


class _GetConversationStub:
    def __init__(self, detail: ConversationDetail) -> None:
        self._detail = detail

    async def execute(self, project_id: uuid.UUID, session_id: str) -> ConversationDetail:
        return self._detail


def _two_turn_detail(project_id: uuid.UUID, session_id: str) -> ConversationDetail:
    now = datetime.now(UTC)
    turns = [
        ConversationTurn(
            trace_id="t1",
            start_time=now,
            question="Do we have Pro?",
            answer="Yes.",
            user_id=None,
            live_interaction_id=None,
            search_query=None,
        ),
        ConversationTurn(
            trace_id="t2",
            start_time=now,
            question="How much does it cost?",
            answer="About 10 dollars.",
            user_id=None,
            live_interaction_id=None,
            search_query=None,
        ),
    ]
    summary = ConversationSummary(
        session_id=session_id,
        user_id=None,
        environment=None,
        turn_count=2,
        started_at=now,
        last_activity_at=now,
        conversation_id=None,
        judge_status=None,
        failing_score_kinds=(),
    )
    return ConversationDetail(
        summary=summary,
        conversation=None,
        turns=turns,
        scores=[],
        live_interactions=[],
    )


async def _promote_setup() -> tuple[PromoteConversation, uuid.UUID, uuid.UUID, str]:
    project_id = uuid.uuid4()
    session_id = "sess-1"
    datasets = InMemoryDatasetRepository()
    dataset = Dataset.create(project_id, "chat-gold", task_type="rag_chat")
    await datasets.add(dataset)
    detail = _two_turn_detail(project_id, session_id)
    promote = PromoteConversation(
        _GetConversationStub(detail),
        datasets,
        AddDatasetItem(datasets, InMemoryExperimentRepository(), InMemoryEvaluationRunRepository()),
    )
    return promote, project_id, dataset.id, session_id


@pytest.mark.asyncio
async def test_promote_mode_full_keeps_prior_turns_as_history() -> None:
    promote, project_id, dataset_id, session_id = await _promote_setup()
    item = await promote.execute(
        PromoteConversationCommand(
            project_id=project_id,
            session_id=session_id,
            dataset_id=dataset_id,
            expected_output="8 dollars per user per month.",
            expected_doc_ids=["plans"],
            mode="full",
        )
    )
    assert isinstance(item.input, RagChatInput)
    assert item.input.question == "How much does it cost?"
    assert [(t.role, t.content) for t in item.input.history] == [
        ("user", "Do we have Pro?"),
        ("assistant", "Yes."),
    ]
    assert item.actual_output == "About 10 dollars."


@pytest.mark.asyncio
async def test_promote_mode_last_turn_has_empty_history() -> None:
    promote, project_id, dataset_id, session_id = await _promote_setup()
    item = await promote.execute(
        PromoteConversationCommand(
            project_id=project_id,
            session_id=session_id,
            dataset_id=dataset_id,
            expected_output="8 dollars per user per month.",
            expected_doc_ids=["plans"],
            mode="last_turn",
        )
    )
    assert isinstance(item.input, RagChatInput)
    assert item.input.question == "How much does it cost?"
    assert item.input.history == []
    assert item.actual_output == "About 10 dollars."
