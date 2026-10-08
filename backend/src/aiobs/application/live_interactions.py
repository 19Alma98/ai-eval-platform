from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from aiobs.application.datasets import AddDatasetItem, AddDatasetItemCommand, DatasetNotFoundError
from aiobs.application.evaluators import CreateEvaluator, CreateEvaluatorCommand
from aiobs.application.metrics_sets import (
    EnsureProjectDefaultMetricsSet,
    MetricsSetNotFoundError,
)
from aiobs.application.projects import ProjectNotFoundError
from aiobs.domain.dataset import DatasetItem
from aiobs.domain.live_interaction import (
    GOLDLESS_METRIC_KINDS,
    LiveInteraction,
    LiveInteractionScore,
    LiveReview,
    filter_goldless_entries,
)
from aiobs.domain.metrics_set import MetricsSet, MetricsSetEntry
from aiobs.domain.repositories import (
    DatasetRepository,
    EvaluatorRepository,
    LiveInteractionRepository,
    MetricsSetRepository,
    ProjectRepository,
)
from aiobs.domain.retrieval import normalize_documents
from aiobs.evaluation.protocol import EvaluationSample
from aiobs.evaluation.registry import create_evaluator

logger = logging.getLogger(__name__)


class LiveInteractionNotFoundError(Exception):
    def __init__(self, interaction_id: uuid.UUID) -> None:
        self.interaction_id = interaction_id
        super().__init__(f"Live interaction not found: {interaction_id}")


@dataclass(frozen=True, slots=True)
class SubmitLiveInteractionCommand:
    project_id: uuid.UUID
    question: str
    answer: str
    documents: list[dict[str, Any]] | None = None
    metadata: dict[str, Any] | None = None
    external_id: str | None = None
    metrics_set_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class SubmitLiveInteractionResult:
    interaction: LiveInteraction
    created: bool


@dataclass(frozen=True, slots=True)
class LiveInteractionDetail:
    interaction: LiveInteraction
    scores: list[LiveInteractionScore]
    review: LiveReview | None


@dataclass(frozen=True, slots=True)
class PromoteLiveInteractionCommand:
    interaction_id: uuid.UUID
    dataset_id: uuid.UUID
    expected_output: Any | None = None


@dataclass(frozen=True, slots=True)
class UpsertLiveReviewCommand:
    interaction_id: uuid.UUID
    verdict: str
    note: str | None = None
    reviewer: str | None = None


def _evaluator_type_for_kind(kind: str) -> str:
    if kind in GOLDLESS_METRIC_KINDS:
        return "llm_judge"
    return "deterministic"


async def _find_evaluator_by_kind(
    evaluators: EvaluatorRepository,
    project_id: uuid.UUID,
    kind: str,
) -> Any:
    for evaluator in await evaluators.list_by_project(project_id):
        if evaluator.name == kind and str(evaluator.config.get("kind", "")).strip() == kind:
            return evaluator
    return None


async def _ensure_goldless_evaluator_ids(
    metrics_set: MetricsSet,
    entries: list[MetricsSetEntry],
    evaluators: EvaluatorRepository,
    create_evaluator_uc: CreateEvaluator,
) -> list[MetricsSetEntry]:
    resolved: list[MetricsSetEntry] = []
    for entry in entries:
        if entry.evaluator_id is not None:
            resolved.append(entry)
            continue
        evaluator = await _find_evaluator_by_kind(evaluators, metrics_set.project_id, entry.kind)
        if evaluator is None:
            evaluator = await create_evaluator_uc.execute(
                CreateEvaluatorCommand(
                    project_id=metrics_set.project_id,
                    name=entry.kind,
                    type=_evaluator_type_for_kind(entry.kind),
                    config={**dict(entry.config), "kind": entry.kind},
                )
            )
        from dataclasses import replace

        resolved.append(replace(entry, evaluator_id=evaluator.id))
    return resolved


def score_is_failed(score: LiveInteractionScore) -> bool:
    label = (score.label or "").strip().upper()
    if label == "FAIL":
        return True
    if score.threshold is not None and score.score is not None:
        return score.score < score.threshold
    return False


class SubmitLiveInteraction:
    def __init__(
        self,
        projects: ProjectRepository,
        live: LiveInteractionRepository,
        metrics_sets: MetricsSetRepository,
    ) -> None:
        self._projects = projects
        self._live = live
        self._metrics_sets = metrics_sets

    async def execute(self, command: SubmitLiveInteractionCommand) -> SubmitLiveInteractionResult:
        project = await self._projects.get_by_id(command.project_id)
        if project is None:
            raise ProjectNotFoundError(command.project_id)

        if command.external_id:
            existing = await self._live.get_by_external_id(
                command.project_id, command.external_id.strip()
            )
            if existing is not None:
                return SubmitLiveInteractionResult(interaction=existing, created=False)

        if command.metrics_set_id is not None:
            ms = await self._metrics_sets.get_by_id(command.metrics_set_id)
            if ms is None or ms.project_id != command.project_id:
                raise MetricsSetNotFoundError(command.metrics_set_id)

        docs = normalize_documents(command.documents or [])
        interaction = LiveInteraction.create(
            command.project_id,
            command.question,
            command.answer,
            documents=docs,
            metadata=command.metadata,
            external_id=command.external_id,
            metrics_set_id=command.metrics_set_id,
        )
        saved = await self._live.add(interaction)
        return SubmitLiveInteractionResult(interaction=saved, created=True)


class ScoreLiveInteraction:
    def __init__(
        self,
        live: LiveInteractionRepository,
        metrics_sets: MetricsSetRepository,
        evaluators: EvaluatorRepository,
        create_evaluator: CreateEvaluator,
        ensure_default: EnsureProjectDefaultMetricsSet,
    ) -> None:
        self._live = live
        self._metrics_sets = metrics_sets
        self._evaluators = evaluators
        self._create_evaluator = create_evaluator
        self._ensure_default = ensure_default

    async def execute(self, interaction_id: uuid.UUID) -> LiveInteraction:
        interaction = await self._live.get_by_id(interaction_id)
        if interaction is None:
            raise LiveInteractionNotFoundError(interaction_id)

        interaction = await self._live.update(
            interaction.with_status(
                "running",
                error_message=None,
                score_warning=None,
            )
        )

        try:
            metrics_set = await self._resolve_metrics_set(interaction)
            goldless = filter_goldless_entries(list(metrics_set.entries))
            if not goldless:
                interaction = await self._live.update(
                    interaction.with_status(
                        "scored",
                        metrics_set_id=metrics_set.id,
                        score_warning="No gold-less metrics enabled in the metrics set "
                        f"(allowlist: {', '.join(sorted(GOLDLESS_METRIC_KINDS))})",
                        error_message=None,
                        scored_at=datetime.now(UTC),
                    )
                )
                await self._live.replace_scores(interaction.id, [])
                return interaction

            resolved_entries = await _ensure_goldless_evaluator_ids(
                metrics_set,
                goldless,
                self._evaluators,
                self._create_evaluator,
            )
            sample = EvaluationSample(
                input=interaction.question,
                expected_output=None,
                actual_output=interaction.answer,
                context={"documents": interaction.documents},
                metadata=dict(interaction.metadata),
            )
            scores: list[LiveInteractionScore] = []
            for entry in resolved_entries:
                entity = await self._evaluators.get_by_id(entry.evaluator_id)  # type: ignore[arg-type]
                if entity is None:
                    continue
                kind = str(entity.config.get("kind", entry.kind)).strip()
                # Entry config (e.g. judge model) overrides the shared per-kind evaluator.
                config = {**entity.config, **entry.config, "kind": kind}
                evaluator = create_evaluator(kind, config)
                result = await evaluator.evaluate(sample)
                scores.append(
                    LiveInteractionScore.create(
                        interaction.id,
                        kind=entry.kind,
                        evaluator_id=entity.id,
                        score=result.score,
                        label=result.label,
                        explanation=result.explanation,
                        threshold=entry.threshold,
                    )
                )

            await self._live.replace_scores(interaction.id, scores)
            return await self._live.update(
                interaction.with_status(
                    "scored",
                    metrics_set_id=metrics_set.id,
                    score_warning=None,
                    error_message=None,
                    scored_at=datetime.now(UTC),
                )
            )
        except Exception as exc:
            logger.exception("Live interaction scoring failed: %s", interaction_id)
            return await self._live.update(
                interaction.with_status(
                    "error",
                    error_message=str(exc)[:2000],
                    scored_at=datetime.now(UTC),
                )
            )

    async def _resolve_metrics_set(self, interaction: LiveInteraction) -> MetricsSet:
        if interaction.metrics_set_id is not None:
            ms = await self._metrics_sets.get_by_id(interaction.metrics_set_id)
            if ms is None or ms.project_id != interaction.project_id:
                raise MetricsSetNotFoundError(interaction.metrics_set_id)
            return ms
        return await self._ensure_default.execute(interaction.project_id)


class ListLiveInteractions:
    def __init__(self, live: LiveInteractionRepository) -> None:
        self._live = live

    async def execute(
        self,
        project_id: uuid.UUID,
        *,
        judge_status: str | None = None,
        search: str | None = None,
        failed_only: bool = False,
        limit: int = 50,
    ) -> list[tuple[LiveInteraction, list[LiveInteractionScore], LiveReview | None]]:
        items = await self._live.list_by_project(
            project_id,
            judge_status=judge_status,
            search=search,
            limit=limit if not failed_only else min(limit * 3, 200),
        )
        out: list[tuple[LiveInteraction, list[LiveInteractionScore], LiveReview | None]] = []
        for item in items:
            scores = await self._live.list_scores(item.id)
            review = await self._live.get_review(item.id)
            if failed_only and not any(score_is_failed(s) for s in scores):
                continue
            out.append((item, scores, review))
            if len(out) >= limit:
                break
        return out


class GetLiveInteraction:
    def __init__(self, live: LiveInteractionRepository) -> None:
        self._live = live

    async def execute(self, interaction_id: uuid.UUID) -> LiveInteractionDetail:
        interaction = await self._live.get_by_id(interaction_id)
        if interaction is None:
            raise LiveInteractionNotFoundError(interaction_id)
        scores = await self._live.list_scores(interaction_id)
        review = await self._live.get_review(interaction_id)
        return LiveInteractionDetail(
            interaction=interaction,
            scores=scores,
            review=review,
        )


class UpsertLiveReview:
    def __init__(self, live: LiveInteractionRepository) -> None:
        self._live = live

    async def execute(self, command: UpsertLiveReviewCommand) -> LiveReview:
        interaction = await self._live.get_by_id(command.interaction_id)
        if interaction is None:
            raise LiveInteractionNotFoundError(command.interaction_id)
        review = LiveReview.create(
            command.interaction_id,
            command.verdict,
            note=command.note,
            reviewer=command.reviewer,
        )
        return await self._live.upsert_review(review)


class PromoteLiveInteraction:
    def __init__(
        self,
        live: LiveInteractionRepository,
        datasets: DatasetRepository,
        add_item: AddDatasetItem,
    ) -> None:
        self._live = live
        self._datasets = datasets
        self._add_item = add_item

    async def execute(self, command: PromoteLiveInteractionCommand) -> DatasetItem:
        interaction = await self._live.get_by_id(command.interaction_id)
        if interaction is None:
            raise LiveInteractionNotFoundError(command.interaction_id)
        dataset = await self._datasets.get_by_id(command.dataset_id)
        if dataset is None:
            raise DatasetNotFoundError(command.dataset_id)
        if dataset.project_id != interaction.project_id:
            raise DatasetNotFoundError(command.dataset_id)

        doc_ids = [
            str(d["id"])
            for d in interaction.documents
            if isinstance(d, dict) and d.get("id") is not None
        ]
        metadata: dict[str, Any] = {
            "source_live_interaction_id": str(interaction.id),
        }
        if doc_ids:
            metadata["expected_doc_ids"] = doc_ids

        expected = (
            command.expected_output if command.expected_output is not None else interaction.answer
        )
        return await self._add_item.execute(
            AddDatasetItemCommand(
                dataset_id=command.dataset_id,
                input=interaction.question,
                expected_output=expected,
                metadata=metadata,
            )
        )


async def schedule_live_score(interaction_id: uuid.UUID) -> None:
    """BackgroundTasks entrypoint — opens a dedicated DB session."""
    from aiobs.application.evaluators import CreateEvaluator
    from aiobs.application.metrics_sets import EnsureProjectDefaultMetricsSet
    from aiobs.infrastructure.db import get_session_factory
    from aiobs.infrastructure.repositories import (
        SqlAlchemyEvaluatorRepository,
        SqlAlchemyLiveInteractionRepository,
        SqlAlchemyMetricsSetRepository,
        SqlAlchemyProjectRepository,
    )

    try:
        factory = get_session_factory()
    except RuntimeError:
        logger.warning(
            "Skipping background live score; DB session factory not initialized (%s)",
            interaction_id,
        )
        return

    async with factory() as session:
        live = SqlAlchemyLiveInteractionRepository(session)
        metrics_sets = SqlAlchemyMetricsSetRepository(session)
        evaluators = SqlAlchemyEvaluatorRepository(session)
        projects = SqlAlchemyProjectRepository(session)
        create_evaluator_uc = CreateEvaluator(evaluators, projects)
        ensure_default = EnsureProjectDefaultMetricsSet(
            metrics_sets, evaluators, projects, create_evaluator_uc
        )
        scorer = ScoreLiveInteraction(
            live,
            metrics_sets,
            evaluators,
            create_evaluator_uc,
            ensure_default,
        )
        try:
            await scorer.execute(interaction_id)
        except Exception:
            logger.exception("Background live score failed: %s", interaction_id)
