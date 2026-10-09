from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import datetime

import pytest
from httpx2 import ASGITransport, AsyncClient

from aiobs_server.api.deps import (
    get_dataset_repository,
    get_evaluator_repository,
    get_live_interaction_repository,
    get_metrics_set_repository,
    get_project_repository,
)
from aiobs_server.domain.dataset import Dataset, DatasetItem
from aiobs_server.domain.live_interaction import (
    LiveInteraction,
    LiveInteractionScore,
    LiveReview,
    LiveScoreReview,
)
from aiobs_server.domain.project import Project
from aiobs_server.evaluation import bootstrap_evaluators
from aiobs_server.evaluation.registry import clear_registry
from aiobs_server.main import create_app
from support.fake_llm import ScriptedJudgeLlm
from support.repositories import InMemoryEvaluatorRepository, InMemoryMetricsSetRepository

FakeLlm = ScriptedJudgeLlm


class InMemoryProjectRepository:
    def __init__(self) -> None:
        self._items: dict[uuid.UUID, Project] = {}

    async def add(self, project: Project) -> Project:
        self._items[project.id] = project
        return project

    async def get_by_id(self, project_id: uuid.UUID) -> Project | None:
        return self._items.get(project_id)

    async def get_by_slug(self, slug: str) -> Project | None:
        for p in self._items.values():
            if p.slug == slug:
                return p
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
        self._score_reviews: dict[uuid.UUID, LiveScoreReview] = {}

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
        offset: int = 0,
    ) -> list[LiveInteraction]:
        rows = [i for i in self._items.values() if i.project_id == project_id]
        if judge_status:
            rows = [i for i in rows if i.judge_status == judge_status]
        if search:
            rows = [i for i in rows if search.lower() in i.question.lower()]
        rows.sort(key=lambda i: i.created_at, reverse=True)
        return rows[offset : offset + limit]

    async def replace_scores(
        self, interaction_id: uuid.UUID, scores: list[LiveInteractionScore]
    ) -> list[LiveInteractionScore]:
        for old in self._scores.get(interaction_id, []):
            self._score_reviews.pop(old.id, None)
        self._scores[interaction_id] = list(scores)
        return list(scores)

    async def list_scores(self, interaction_id: uuid.UUID) -> list[LiveInteractionScore]:
        return list(self._scores.get(interaction_id, []))

    async def list_recent_scores_by_kind(
        self,
        project_id: uuid.UUID,
        *,
        limit_per_kind: int = 50,
    ) -> dict[str, list[LiveInteractionScore]]:
        by_kind: dict[str, list[LiveInteractionScore]] = {}
        for interaction in self._items.values():
            if interaction.project_id != project_id:
                continue
            for score in self._scores.get(interaction.id, []):
                by_kind.setdefault(score.kind, []).append(score)
        for kind, scores in by_kind.items():
            scores.sort(key=lambda s: (s.created_at, s.id), reverse=True)
            by_kind[kind] = scores[: max(1, limit_per_kind)]
        return by_kind

    async def get_score(self, score_id: uuid.UUID) -> LiveInteractionScore | None:
        for scores in self._scores.values():
            for score in scores:
                if score.id == score_id:
                    return score
        return None

    async def upsert_review(self, review: LiveReview) -> LiveReview:
        self._reviews[review.live_interaction_id] = review
        return review

    async def get_review(self, interaction_id: uuid.UUID) -> LiveReview | None:
        return self._reviews.get(interaction_id)

    async def upsert_score_review(self, review: LiveScoreReview) -> LiveScoreReview:
        self._score_reviews[review.live_interaction_score_id] = review
        return review

    async def get_score_review(self, score_id: uuid.UUID) -> LiveScoreReview | None:
        return self._score_reviews.get(score_id)

    async def list_score_reviews_by_score_ids(
        self, score_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, LiveScoreReview]:
        return {sid: self._score_reviews[sid] for sid in score_ids if sid in self._score_reviews}

    async def list_calibration_rows(
        self,
        project_id: uuid.UUID,
        *,
        since: datetime,
    ) -> list[tuple[LiveInteractionScore, LiveScoreReview]]:
        out: list[tuple[LiveInteractionScore, LiveScoreReview]] = []
        for interaction in self._items.values():
            if interaction.project_id != project_id:
                continue
            for score in self._scores.get(interaction.id, []):
                review = self._score_reviews.get(score.id)
                if review is None or review.created_at < since:
                    continue
                out.append((score, review))
        out.sort(key=lambda pair: pair[1].created_at, reverse=True)
        return out


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


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    projects = InMemoryProjectRepository()
    live = InMemoryLiveRepository()
    metrics = InMemoryMetricsSetRepository()
    evaluators = InMemoryEvaluatorRepository()
    datasets = InMemoryDatasetRepository()

    app = create_app()
    # Override LiteLLM judges registered in create_app with a fake client.
    clear_registry()
    bootstrap_evaluators(FakeLlm())

    app.dependency_overrides[get_project_repository] = lambda: projects
    app.dependency_overrides[get_live_interaction_repository] = lambda: live
    app.dependency_overrides[get_metrics_set_repository] = lambda: metrics
    app.dependency_overrides[get_evaluator_repository] = lambda: evaluators
    app.dependency_overrides[get_dataset_repository] = lambda: datasets

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
    clear_registry()


@pytest.mark.asyncio
async def test_submit_rescore_review_promote(client: AsyncClient) -> None:
    proj = await client.post("/api/v1/projects", json={"name": "Live", "slug": "live"})
    assert proj.status_code == 201
    project_id = proj.json()["id"]

    ds = await client.post(
        f"/api/v1/projects/{project_id}/datasets",
        json={"name": "gold", "task_type": "rag_qa"},
    )
    assert ds.status_code == 201
    dataset_id = ds.json()["id"]

    ensure = await client.post(f"/api/v1/projects/{project_id}/metrics-pack/ensure")
    assert ensure.status_code == 200, ensure.text

    submit = await client.post(
        f"/api/v1/projects/{project_id}/live-interactions",
        json={
            "question": "What is PTO?",
            "answer": "Paid time off",
            "documents": [{"id": "doc-1", "text": "PTO means paid time off"}],
            "external_id": "ext-1",
        },
    )
    assert submit.status_code == 202
    body = submit.json()
    assert body["judge_status"] == "pending"
    interaction_id = body["id"]

    again = await client.post(
        f"/api/v1/projects/{project_id}/live-interactions",
        json={
            "question": "other",
            "answer": "other",
            "external_id": "ext-1",
        },
    )
    assert again.status_code == 202
    assert again.json()["id"] == interaction_id

    scored = await client.post(f"/api/v1/live-interactions/{interaction_id}/rescore")
    assert scored.status_code == 200
    scored_body = scored.json()
    assert scored_body["judge_status"] == "scored"
    assert any(s["kind"] == "groundedness" for s in scored_body["scores"])
    assert "metadata" in scored_body["scores"][0]

    review = await client.post(
        f"/api/v1/live-interactions/{interaction_id}/review",
        json={"verdict": "disagree", "note": "needs work"},
    )
    assert review.status_code == 200
    assert review.json()["verdict"] == "disagree"

    missing_gold = await client.post(
        f"/api/v1/live-interactions/{interaction_id}/promote",
        json={"dataset_id": dataset_id},
    )
    assert missing_gold.status_code == 422

    promote = await client.post(
        f"/api/v1/live-interactions/{interaction_id}/promote",
        json={
            "dataset_id": dataset_id,
            "expected_output": "Paid time off",
            "expected_doc_ids": ["doc-1"],
        },
    )
    assert promote.status_code == 201, promote.text
    assert promote.json()["metadata"]["expected_doc_ids"] == ["doc-1"]
    assert promote.json()["metadata"]["retrieved_doc_ids_at_promotion"] == ["doc-1"]

    listed = await client.get(f"/api/v1/projects/{project_id}/live-interactions")
    assert listed.status_code == 200
    listed_body = listed.json()
    assert "items" in listed_body
    assert "judge_warnings" in listed_body
    assert len(listed_body["items"]) == 1
    assert listed_body["judge_warnings"] == []


@pytest.mark.asyncio
async def test_score_review_and_calibration(client: AsyncClient) -> None:
    proj = await client.post("/api/v1/projects", json={"name": "Calib", "slug": "calib"})
    assert proj.status_code == 201
    project_id = proj.json()["id"]

    ensure = await client.post(f"/api/v1/projects/{project_id}/metrics-pack/ensure")
    assert ensure.status_code == 200, ensure.text

    submit = await client.post(
        f"/api/v1/projects/{project_id}/live-interactions",
        json={
            "question": "What is PTO?",
            "answer": "Paid time off",
            "documents": [{"id": "doc-1", "text": "PTO means paid time off"}],
        },
    )
    assert submit.status_code == 202
    interaction_id = submit.json()["id"]

    scored = await client.post(f"/api/v1/live-interactions/{interaction_id}/rescore")
    assert scored.status_code == 200
    scores = scored.json()["scores"]
    assert scores
    score_id = scores[0]["id"]
    old_score_ids = {s["id"] for s in scores}

    review = await client.post(
        f"/api/v1/live-interaction-scores/{score_id}/review",
        json={
            "verdict": "agree",
            "corrected_explanation": "Clear and grounded in the doc.",
        },
    )
    assert review.status_code == 200
    assert review.json()["verdict"] == "agree"
    assert review.json()["corrected_explanation"] == "Clear and grounded in the doc."

    detail = await client.get(f"/api/v1/live-interactions/{interaction_id}")
    assert detail.status_code == 200
    nested = next(s for s in detail.json()["scores"] if s["id"] == score_id)
    assert nested["review"]["verdict"] == "agree"

    calib = await client.get(f"/api/v1/projects/{project_id}/live-interactions/calibration")
    assert calib.status_code == 200
    buckets = calib.json()
    assert len(buckets) >= 1
    bucket = next(b for b in buckets if b["kind"] == scores[0]["kind"])
    assert bucket["n_reviewed"] == 1
    assert bucket["n_agree"] == 1
    assert bucket["agreement_rate"] == 1.0
    assert bucket["n_explanation_edits"] == 1

    rescored = await client.post(f"/api/v1/live-interactions/{interaction_id}/rescore")
    assert rescored.status_code == 200
    new_ids = {s["id"] for s in rescored.json()["scores"]}
    assert old_score_ids.isdisjoint(new_ids)

    missing = await client.post(
        f"/api/v1/live-interaction-scores/{score_id}/review",
        json={"verdict": "disagree"},
    )
    assert missing.status_code == 404

    empty_calib = await client.get(f"/api/v1/projects/{project_id}/live-interactions/calibration")
    assert empty_calib.status_code == 200
    assert empty_calib.json() == []
