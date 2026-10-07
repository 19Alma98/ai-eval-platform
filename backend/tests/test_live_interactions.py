from __future__ import annotations

import uuid
from dataclasses import replace

import pytest

from aiobs.application.datasets import AddDatasetItem
from aiobs.application.evaluators import CreateEvaluator
from aiobs.application.live_interactions import (
    PromoteLiveInteraction,
    PromoteLiveInteractionCommand,
    ScoreLiveInteraction,
    SubmitLiveInteraction,
    SubmitLiveInteractionCommand,
    UpsertLiveReview,
    UpsertLiveReviewCommand,
)
from aiobs.application.metrics_sets import EnsureProjectDefaultMetricsSet
from aiobs.domain.dataset import Dataset, DatasetItem
from aiobs.domain.evaluator import Evaluator
from aiobs.domain.live_interaction import (
    GOLDLESS_METRIC_KINDS,
    LiveInteraction,
    LiveInteractionScore,
    LiveReview,
    filter_goldless_entries,
)
from aiobs.domain.metrics_set import MetricsSet, MetricsSetEntry
from aiobs.domain.project import Project
from aiobs.evaluation import bootstrap_evaluators
from aiobs.evaluation.registry import clear_registry


class FakeLlm:
    async def complete_json(self, *, system: str, user: str, model: str | None = None) -> dict:
        return {"score": 0.9, "label": "PASS", "explanation": "ok"}


class InMemoryProjectRepository:
    def __init__(self) -> None:
        self._items: dict[uuid.UUID, Project] = {}

    async def add(self, project: Project) -> Project:
        self._items[project.id] = project
        return project

    async def get_by_id(self, project_id: uuid.UUID) -> Project | None:
        return self._items.get(project_id)

    async def get_by_slug(self, slug: str) -> Project | None:
        return None

    async def list_all(self) -> list[Project]:
        return list(self._items.values())

    async def delete(self, project_id: uuid.UUID) -> bool:
        return self._items.pop(project_id, None) is not None


class InMemoryLiveRepository:
    def __init__(self) -> None:
        self._items: dict[uuid.UUID, LiveInteraction] = {}
        self._scores: dict[uuid.UUID, list[LiveInteractionScore]] = {}
        self._reviews: dict[uuid.UUID, LiveReview] = {}

    async def add(self, interaction: LiveInteraction) -> LiveInteraction:
        self._items[interaction.id] = interaction
        return interaction

    async def update(self, interaction: LiveInteraction) -> LiveInteraction:
        self._items[interaction.id] = interaction
        return interaction

    async def get_by_id(self, interaction_id: uuid.UUID) -> LiveInteraction | None:
        return self._items.get(interaction_id)

    async def get_by_external_id(
        self, project_id: uuid.UUID, external_id: str
    ) -> LiveInteraction | None:
        for item in self._items.values():
            if item.project_id == project_id and item.external_id == external_id:
                return item
        return None

    async def list_by_project(
        self,
        project_id: uuid.UUID,
        *,
        judge_status: str | None = None,
        search: str | None = None,
        limit: int = 50,
    ) -> list[LiveInteraction]:
        rows = [i for i in self._items.values() if i.project_id == project_id]
        if judge_status:
            rows = [i for i in rows if i.judge_status == judge_status]
        if search:
            rows = [i for i in rows if search.lower() in i.question.lower()]
        rows.sort(key=lambda i: i.created_at, reverse=True)
        return rows[:limit]

    async def replace_scores(
        self, interaction_id: uuid.UUID, scores: list[LiveInteractionScore]
    ) -> list[LiveInteractionScore]:
        self._scores[interaction_id] = list(scores)
        return list(scores)

    async def list_scores(self, interaction_id: uuid.UUID) -> list[LiveInteractionScore]:
        return list(self._scores.get(interaction_id, []))

    async def upsert_review(self, review: LiveReview) -> LiveReview:
        self._reviews[review.live_interaction_id] = review
        return review

    async def get_review(self, interaction_id: uuid.UUID) -> LiveReview | None:
        return self._reviews.get(interaction_id)


class InMemoryMetricsSetRepository:
    def __init__(self) -> None:
        self._items: dict[uuid.UUID, MetricsSet] = {}

    async def add(self, metrics_set: MetricsSet) -> MetricsSet:
        self._items[metrics_set.id] = metrics_set
        return metrics_set

    async def get_by_id(self, metrics_set_id: uuid.UUID) -> MetricsSet | None:
        return self._items.get(metrics_set_id)

    async def get_project_default(self, project_id: uuid.UUID) -> MetricsSet | None:
        for s in self._items.values():
            if s.project_id == project_id and s.is_project_default:
                return s
        return None

    async def list_by_project(self, project_id: uuid.UUID) -> list[MetricsSet]:
        return [s for s in self._items.values() if s.project_id == project_id]

    async def update(self, metrics_set: MetricsSet) -> MetricsSet:
        self._items[metrics_set.id] = metrics_set
        return metrics_set

    async def delete(self, metrics_set_id: uuid.UUID) -> None:
        self._items.pop(metrics_set_id, None)

    async def next_version(self, project_id: uuid.UUID, name: str) -> int:
        return 1


class InMemoryEvaluatorRepository:
    def __init__(self) -> None:
        self._items: dict[uuid.UUID, Evaluator] = {}

    async def add(self, evaluator: Evaluator) -> Evaluator:
        self._items[evaluator.id] = evaluator
        return evaluator

    async def get_by_id(self, evaluator_id: uuid.UUID) -> Evaluator | None:
        return self._items.get(evaluator_id)

    async def list_by_project(self, project_id: uuid.UUID) -> list[Evaluator]:
        return [e for e in self._items.values() if e.project_id == project_id]

    async def get_by_ids(self, evaluator_ids: list[uuid.UUID]) -> list[Evaluator]:
        return [self._items[i] for i in evaluator_ids if i in self._items]


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
        self, project_id: uuid.UUID, *, task_type: str | None = None
    ) -> list[Dataset]:
        return [d for d in self._datasets.values() if d.project_id == project_id]

    async def add_item(self, item: DatasetItem) -> DatasetItem:
        self._items[item.id] = item
        return item

    async def list_items(self, dataset_id: uuid.UUID) -> list[DatasetItem]:
        return [i for i in self._items.values() if i.dataset_id == dataset_id]

    async def get_item(self, item_id: uuid.UUID) -> DatasetItem | None:
        return self._items.get(item_id)


def test_filter_goldless_entries() -> None:
    entries = [
        MetricsSetEntry(
            id=uuid.uuid4(),
            kind="groundedness",
            enabled=True,
            threshold=0.7,
            config={},
            evaluator_id=None,
            is_default=True,
        ),
        MetricsSetEntry(
            id=uuid.uuid4(),
            kind="correctness",
            enabled=True,
            threshold=0.7,
            config={},
            evaluator_id=None,
            is_default=True,
        ),
        MetricsSetEntry(
            id=uuid.uuid4(),
            kind="answer_relevance",
            enabled=False,
            threshold=0.7,
            config={},
            evaluator_id=None,
            is_default=True,
        ),
    ]
    filtered = filter_goldless_entries(entries)
    assert [e.kind for e in filtered] == ["groundedness"]
    assert GOLDLESS_METRIC_KINDS == frozenset({"groundedness", "answer_relevance"})


@pytest.mark.asyncio
async def test_submit_idempotent_by_external_id() -> None:
    projects = InMemoryProjectRepository()
    live = InMemoryLiveRepository()
    metrics = InMemoryMetricsSetRepository()
    project = Project.create("Demo", slug="demo")
    await projects.add(project)

    submit = SubmitLiveInteraction(projects, live, metrics)
    first = await submit.execute(
        SubmitLiveInteractionCommand(
            project_id=project.id,
            question="What is PTO?",
            answer="Paid time off",
            documents=[{"id": "doc-1", "text": "PTO means paid time off"}],
            external_id="turn-1",
        )
    )
    second = await submit.execute(
        SubmitLiveInteractionCommand(
            project_id=project.id,
            question="ignored",
            answer="ignored",
            external_id="turn-1",
        )
    )
    assert first.created is True
    assert second.created is False
    assert first.interaction.id == second.interaction.id
    assert first.interaction.judge_status == "pending"


@pytest.mark.asyncio
async def test_score_goldless_and_review_promote() -> None:
    clear_registry()
    bootstrap_evaluators(FakeLlm())

    projects = InMemoryProjectRepository()
    live = InMemoryLiveRepository()
    metrics = InMemoryMetricsSetRepository()
    evaluators = InMemoryEvaluatorRepository()
    datasets = InMemoryDatasetRepository()

    project = Project.create("Demo", slug="demo")
    await projects.add(project)
    dataset = Dataset.create(project.id, "gold")
    await datasets.add(dataset)

    create_eval = CreateEvaluator(evaluators, projects)
    ensure = EnsureProjectDefaultMetricsSet(metrics, evaluators, projects, create_eval)
    await ensure.execute(project.id)

    submit = SubmitLiveInteraction(projects, live, metrics)
    result = await submit.execute(
        SubmitLiveInteractionCommand(
            project_id=project.id,
            question="What is PTO?",
            answer="Paid time off",
            documents=[{"id": "doc-1", "text": "PTO means paid time off"}],
        )
    )

    scorer = ScoreLiveInteraction(live, metrics, evaluators, create_eval, ensure)
    scored = await scorer.execute(result.interaction.id)
    assert scored.judge_status == "scored"
    scores = await live.list_scores(scored.id)
    kinds = {s.kind for s in scores}
    assert "groundedness" in kinds
    assert "correctness" not in kinds
    assert all(s.label == "PASS" for s in scores if s.kind == "groundedness")

    review_uc = UpsertLiveReview(live)
    review = await review_uc.execute(
        UpsertLiveReviewCommand(
            interaction_id=scored.id,
            verdict="agree",
            note="looks good",
        )
    )
    assert review.verdict == "agree"

    promote = PromoteLiveInteraction(live, datasets, AddDatasetItem(datasets))
    item = await promote.execute(
        PromoteLiveInteractionCommand(interaction_id=scored.id, dataset_id=dataset.id)
    )
    assert item.input == "What is PTO?"
    assert item.expected_output == "Paid time off"
    assert item.metadata["expected_doc_ids"] == ["doc-1"]
    assert item.metadata["source_live_interaction_id"] == str(scored.id)

    clear_registry()


@pytest.mark.asyncio
async def test_score_warns_when_no_goldless_metrics() -> None:
    clear_registry()
    bootstrap_evaluators(FakeLlm())

    projects = InMemoryProjectRepository()
    live = InMemoryLiveRepository()
    metrics = InMemoryMetricsSetRepository()
    evaluators = InMemoryEvaluatorRepository()
    project = Project.create("Demo", slug="demo-2")
    await projects.add(project)

    # Metrics set with only correctness enabled
    entry = MetricsSetEntry(
        id=uuid.uuid4(),
        kind="correctness",
        enabled=True,
        threshold=0.7,
        config={},
        evaluator_id=None,
        is_default=True,
    )
    ms = MetricsSet.create_project_default(project.id)
    ms = replace(ms, entries=(entry,))
    await metrics.add(ms)

    create_eval = CreateEvaluator(evaluators, projects)
    ensure = EnsureProjectDefaultMetricsSet(metrics, evaluators, projects, create_eval)

    submit = SubmitLiveInteraction(projects, live, metrics)
    result = await submit.execute(
        SubmitLiveInteractionCommand(
            project_id=project.id,
            question="Q?",
            answer="A",
            metrics_set_id=ms.id,
        )
    )
    scorer = ScoreLiveInteraction(live, metrics, evaluators, create_eval, ensure)
    scored = await scorer.execute(result.interaction.id)
    assert scored.judge_status == "scored"
    assert scored.score_warning is not None
    assert await live.list_scores(scored.id) == []

    clear_registry()
