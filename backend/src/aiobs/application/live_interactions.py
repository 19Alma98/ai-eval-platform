from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

from aiobs.application.datasets import AddDatasetItem, AddDatasetItemCommand, DatasetNotFoundError
from aiobs.application.evaluators import CreateEvaluator
from aiobs.application.metrics_sets import (
    EnsureProjectDefaultMetricsSet,
    MetricsSetNotFoundError,
    find_or_create_evaluator_for_entry,
)
from aiobs.application.projects import ProjectNotFoundError
from aiobs.domain.dataset import DatasetItem
from aiobs.domain.live_interaction import (
    GOLDLESS_METRIC_KINDS,
    DuplicateExternalIdError,
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
from aiobs.evaluation.judges.errors import JUDGE_OUTPUT_INVALID
from aiobs.evaluation.judges.warnings import JUDGE_MODEL_UNSUITABLE
from aiobs.evaluation.outcomes import item_verdict
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
    # Gold must come from a human: the production answer and retrieved docs are the
    # system under test, so using them as gold makes later evals pass by construction.
    expected_output: Any | None = None
    expected_doc_ids: list[str] | None = None


@dataclass(frozen=True, slots=True)
class UpsertLiveReviewCommand:
    interaction_id: uuid.UUID
    verdict: str
    note: str | None = None
    reviewer: str | None = None


async def _ensure_goldless_evaluator_ids(
    metrics_set: MetricsSet,
    entries: list[MetricsSetEntry],
    evaluators: EvaluatorRepository,
    create_evaluator_uc: CreateEvaluator,
) -> list[MetricsSetEntry]:
    resolved: list[MetricsSetEntry] = []
    in_use = {e.evaluator_id for e in metrics_set.entries if e.evaluator_id is not None}
    for entry in entries:
        if entry.evaluator_id is not None:
            resolved.append(entry)
            continue
        evaluator = await find_or_create_evaluator_for_entry(
            evaluators,
            create_evaluator_uc,
            metrics_set.project_id,
            entry,
            exclude=frozenset(in_use),
        )
        in_use.add(evaluator.id)
        resolved.append(replace(entry, evaluator_id=evaluator.id))
    return resolved


def score_is_failed(score: LiveInteractionScore) -> bool:
    return item_verdict(score.score, score.label, score.threshold) == "FAIL"


def _verdict_explanation(
    explanation: str | None, judge_label: str | None, verdict: str
) -> str | None:
    """Keep the judge's own label visible when the threshold overrides it."""
    if judge_label is None or judge_label.strip().upper() == verdict:
        return explanation
    note = f"[judge label: {judge_label}]"
    return f"{explanation} {note}" if explanation else note


def _live_score_warning(failed_kinds: list[str], unsuitable: list[str]) -> str | None:
    parts: list[str] = []
    if failed_kinds:
        parts.append(f"Judge errors: {', '.join(failed_kinds)}")
    if unsuitable:
        parts.append(
            f"{JUDGE_MODEL_UNSUITABLE}: unusable judge output for {', '.join(unsuitable)}; "
            "use method: rubric or a stronger judge model"
        )
    return ". ".join(parts) or None


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
        try:
            saved = await self._live.add(interaction)
        except DuplicateExternalIdError:
            # A concurrent submit with the same external_id won the insert race.
            existing = await self._live.get_by_external_id(
                command.project_id, interaction.external_id or ""
            )
            if existing is None:
                raise
            return SubmitLiveInteractionResult(interaction=existing, created=False)
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
            failed_kinds: list[str] = []
            unsuitable: list[str] = []
            for entry in resolved_entries:
                entity = await self._evaluators.get_by_id(entry.evaluator_id)  # type: ignore[arg-type]
                if entity is None:
                    continue
                kind = str(entity.config.get("kind", entry.kind)).strip()
                # Entry config (e.g. judge model) overrides the shared per-kind evaluator.
                config = {**entity.config, **entry.config, "kind": kind}
                try:
                    evaluator = create_evaluator(kind, config)
                    result = await evaluator.evaluate(sample)
                except Exception as exc:  # noqa: BLE001 — one judge must not sink the others
                    logger.warning(
                        "Live judge %s failed for %s: %s", entry.kind, interaction_id, exc
                    )
                    failed_kinds.append(entry.kind)
                    scores.append(
                        LiveInteractionScore.create(
                            interaction.id,
                            kind=entry.kind,
                            evaluator_id=entity.id,
                            label="ERROR",
                            explanation=f"{type(exc).__name__}: {exc}"[:2000],
                            threshold=entry.threshold,
                        )
                    )
                    continue
                verdict = item_verdict(result.score, result.label, entry.threshold)
                if verdict == "ERROR":
                    failed_kinds.append(entry.kind)
                    if result.metadata.get("error_type") == JUDGE_OUTPUT_INVALID:
                        unsuitable.append(f"{entry.kind} ({result.metadata.get('method')})")
                scores.append(
                    LiveInteractionScore.create(
                        interaction.id,
                        kind=entry.kind,
                        evaluator_id=entity.id,
                        score=result.score,
                        label=verdict if verdict is not None else result.label,
                        explanation=(
                            _verdict_explanation(result.explanation, result.label, verdict)
                            if verdict is not None
                            else result.explanation
                        ),
                        threshold=entry.threshold,
                        metadata=dict(result.metadata),
                    )
                )

            await self._live.replace_scores(interaction.id, scores)
            if scores and len(failed_kinds) == len(scores):
                return await self._live.update(
                    interaction.with_status(
                        "error",
                        metrics_set_id=metrics_set.id,
                        score_warning=_live_score_warning([], unsuitable),
                        error_message=f"All judges failed: {', '.join(failed_kinds)}",
                        scored_at=datetime.now(UTC),
                    )
                )
            return await self._live.update(
                interaction.with_status(
                    "scored",
                    metrics_set_id=metrics_set.id,
                    score_warning=_live_score_warning(failed_kinds, unsuitable),
                    error_message=None,
                    scored_at=datetime.now(UTC),
                )
            )
        except Exception as exc:
            logger.exception("Live interaction scoring failed: %s", interaction_id)
            # Drop scores from a previous run so they are not shown next to an error.
            await self._live.replace_scores(interaction.id, [])
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
        # failed_only filters after loading scores, so page through until enough
        # failures are found instead of scanning a fixed window.
        page_size = min(max(limit, 50), 200) if failed_only else limit
        offset = 0
        out: list[tuple[LiveInteraction, list[LiveInteractionScore], LiveReview | None]] = []
        while True:
            items = await self._live.list_by_project(
                project_id,
                judge_status=judge_status,
                search=search,
                limit=page_size,
                offset=offset,
            )
            for item in items:
                scores = await self._live.list_scores(item.id)
                if failed_only and not any(score_is_failed(s) for s in scores):
                    continue
                review = await self._live.get_review(item.id)
                out.append((item, scores, review))
                if len(out) >= limit:
                    return out
            if not failed_only or len(items) < page_size:
                return out
            offset += page_size


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
        expected = command.expected_output
        if expected is None or (isinstance(expected, str) and not expected.strip()):
            raise ValueError("expected_output is required to promote (gold must be explicit)")

        interaction = await self._live.get_by_id(command.interaction_id)
        if interaction is None:
            raise LiveInteractionNotFoundError(command.interaction_id)
        dataset = await self._datasets.get_by_id(command.dataset_id)
        if dataset is None:
            raise DatasetNotFoundError(command.dataset_id)
        if dataset.project_id != interaction.project_id:
            raise DatasetNotFoundError(command.dataset_id)

        retrieved_ids = [
            str(d["id"])
            for d in interaction.documents
            if isinstance(d, dict) and d.get("id") is not None
        ]
        metadata: dict[str, Any] = {
            "source_live_interaction_id": str(interaction.id),
        }
        if retrieved_ids:
            # Informational only: hit_at_k reads expected_doc_ids, never this key.
            metadata["retrieved_doc_ids_at_promotion"] = retrieved_ids
        expected_doc_ids = [
            str(doc_id).strip()
            for doc_id in (command.expected_doc_ids or [])
            if str(doc_id).strip()
        ]
        if expected_doc_ids:
            metadata["expected_doc_ids"] = expected_doc_ids

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
