from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

from opengrade_server.application.datasets import (
    AddDatasetItem,
    AddDatasetItemCommand,
    DatasetNotFoundError,
)
from opengrade_server.application.evaluators import CreateEvaluator
from opengrade_server.application.metrics_sets import (
    EnsureProjectDefaultMetricsSet,
    MetricsSetNotFoundError,
    find_or_create_evaluator_for_entry,
)
from opengrade_server.application.projects import ProjectNotFoundError
from opengrade_server.domain.dataset import DatasetItem
from opengrade_server.domain.live_interaction import (
    GOLDLESS_METRIC_KINDS,
    DuplicateExternalIdError,
    LiveInteraction,
    LiveInteractionScore,
    LiveScoreReview,
    filter_goldless_entries,
)
from opengrade_server.domain.metrics_set import MetricsSet, MetricsSetEntry
from opengrade_server.domain.repositories import (
    DatasetRepository,
    EvaluatorRepository,
    LiveInteractionRepository,
    MetricsSetRepository,
    ProjectRepository,
    TraceScoreRepository,
)
from opengrade_server.domain.retrieval import normalize_documents
from opengrade_server.domain.trace_score import TraceScore, trace_score_is_failed
from opengrade_server.evaluation.judges.errors import JUDGE_OUTPUT_INVALID
from opengrade_server.evaluation.judges.warnings import (
    JUDGE_MODEL_UNSUITABLE,
    unsuitable_model_warning,
)
from opengrade_server.evaluation.outcomes import item_verdict
from opengrade_server.evaluation.protocol import EvaluationSample
from opengrade_server.evaluation.registry import create_evaluator

logger = logging.getLogger(__name__)

LIVE_UNSUITABLE_WINDOW = 50


@dataclass(frozen=True, slots=True)
class LiveJudgeWarning:
    kind: str
    warnings: list[str]
    warning_detail: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ListLiveInteractionsResult:
    items: list[
        tuple[
            LiveInteraction,
            list[LiveInteractionScore],
            dict[uuid.UUID, LiveScoreReview],
        ]
    ]
    judge_warnings: list[LiveJudgeWarning]
    # Trace scores (SDK metrics, user feedback) per interaction id, joined on source_trace_id.
    trace_scores: dict[uuid.UUID, list[TraceScore]] = field(default_factory=dict)


class LiveInteractionNotFoundError(Exception):
    def __init__(self, interaction_id: uuid.UUID) -> None:
        self.interaction_id = interaction_id
        super().__init__(f"Live interaction not found: {interaction_id}")


class LiveScoreNotFoundError(Exception):
    def __init__(self, score_id: uuid.UUID) -> None:
        self.score_id = score_id
        super().__init__(f"Live interaction score not found: {score_id}")


@dataclass(frozen=True, slots=True)
class SubmitLiveInteractionCommand:
    project_id: uuid.UUID
    question: str
    answer: str
    documents: list[dict[str, Any]] | None = None
    metadata: dict[str, Any] | None = None
    external_id: str | None = None
    metrics_set_id: uuid.UUID | None = None
    # False stores the interaction as "unsampled" and never schedules the judge.
    judge: bool = True


@dataclass(frozen=True, slots=True)
class SubmitLiveInteractionResult:
    interaction: LiveInteraction
    created: bool


@dataclass(frozen=True, slots=True)
class LiveInteractionDetail:
    interaction: LiveInteraction
    scores: list[LiveInteractionScore]
    score_reviews: dict[uuid.UUID, LiveScoreReview]
    trace_scores: list[TraceScore] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class UpsertLiveScoreReviewCommand:
    score_id: uuid.UUID
    verdict: str
    corrected_explanation: str | None = None
    note: str | None = None
    reviewer: str | None = None


@dataclass(frozen=True, slots=True)
class PromoteLiveInteractionCommand:
    interaction_id: uuid.UUID
    dataset_id: uuid.UUID
    # Gold must come from a human: the production answer and retrieved docs are the
    # system under test, so using them as gold makes later evals pass by construction.
    expected_output: Any | None = None
    expected_doc_ids: list[str] | None = None


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


def live_row_is_failed(
    scores: list[LiveInteractionScore],
    trace_scores: list[TraceScore] | None = None,
) -> bool:
    """True if any judge score fails or any joined trace score is FAIL (SDK / thumbs-down)."""
    if any(score_is_failed(s) for s in scores):
        return True
    return any(trace_score_is_failed(t) for t in (trace_scores or ()))


def source_trace_id(interaction: LiveInteraction) -> str | None:
    """OTel trace id a trace-derived interaction came from (lower-case), if any."""
    value = interaction.metadata.get("source_trace_id")
    if isinstance(value, str) and value.strip():
        return value.strip().lower()
    return None


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
            judge=command.judge,
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

        claimed = await self._live.try_claim_for_scoring(interaction_id)
        if claimed is None:
            existing = await self._live.get_by_id(interaction_id)
            if existing is None:
                raise LiveInteractionNotFoundError(interaction_id)
            return existing
        interaction = claimed

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
                # Live-only: empty retrieval is non-applicable (not ungrounded). Offline
                # GroundednessJudge still FAIL 0 on empty documents (RAG assumption).
                if kind == "groundedness" and not interaction.documents:
                    scores.append(
                        LiveInteractionScore.create(
                            interaction.id,
                            kind=entry.kind,
                            evaluator_id=entity.id,
                            score=None,
                            label="SKIPPED",
                            explanation="no retrieved documents (live)",
                            threshold=entry.threshold,
                        )
                    )
                    continue
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
            await self._live.rollback()
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
    def __init__(
        self, live: LiveInteractionRepository, trace_scores: TraceScoreRepository | None = None
    ) -> None:
        self._live = live
        self._trace_scores = trace_scores

    async def _trace_scores_by_trace(
        self, project_id: uuid.UUID, items: list[LiveInteraction]
    ) -> dict[str, list[TraceScore]]:
        if self._trace_scores is None:
            return {}
        trace_ids = sorted({tid for item in items if (tid := source_trace_id(item))})
        if not trace_ids:
            return {}
        return await self._trace_scores.list_by_trace_ids(project_id, trace_ids)

    async def execute(
        self,
        project_id: uuid.UUID,
        *,
        judge_status: str | None = None,
        search: str | None = None,
        failed_only: bool = False,
        unreviewed_only: bool = False,
        limit: int = 50,
    ) -> ListLiveInteractionsResult:
        # failed_only / unreviewed_only filter after loading scores, so page through
        # until enough rows match instead of scanning a fixed window.
        post_filter = failed_only or unreviewed_only
        page_size = min(max(limit, 50), 200) if post_filter else limit
        offset = 0
        out: list[
            tuple[
                LiveInteraction,
                list[LiveInteractionScore],
                dict[uuid.UUID, LiveScoreReview],
            ]
        ] = []
        joined: dict[uuid.UUID, list[TraceScore]] = {}
        while True:
            items = await self._live.list_by_project(
                project_id,
                judge_status=judge_status,
                search=search,
                limit=page_size,
                offset=offset,
            )
            # One trace-score query per page, not per row.
            by_trace = await self._trace_scores_by_trace(project_id, items)
            for item in items:
                scores = await self._live.list_scores(item.id)
                extra = by_trace.get(source_trace_id(item) or "", [])
                if failed_only and not live_row_is_failed(scores, extra):
                    continue
                score_reviews = await self._live.list_score_reviews_by_score_ids(
                    [s.id for s in scores]
                )
                # Annotation queue: judged answers no human has looked at yet.
                if unreviewed_only and (not scores or score_reviews):
                    continue
                out.append((item, scores, score_reviews))
                if extra:
                    joined[item.id] = extra
                if len(out) >= limit:
                    break
            else:
                if not post_filter or len(items) < page_size:
                    break
                offset += page_size
                continue
            break

        recent_by_kind = await self._live.list_recent_scores_by_kind(
            project_id,
            limit_per_kind=LIVE_UNSUITABLE_WINDOW,
        )
        judge_warnings: list[LiveJudgeWarning] = []
        for kind in sorted(recent_by_kind):
            detail = unsuitable_model_warning(recent_by_kind[kind])
            if detail is None:
                continue
            judge_warnings.append(
                LiveJudgeWarning(
                    kind=kind,
                    warnings=[JUDGE_MODEL_UNSUITABLE],
                    warning_detail=detail,
                )
            )
        return ListLiveInteractionsResult(
            items=out, judge_warnings=judge_warnings, trace_scores=joined
        )


class GetLiveInteraction:
    def __init__(
        self, live: LiveInteractionRepository, trace_scores: TraceScoreRepository | None = None
    ) -> None:
        self._live = live
        self._trace_scores = trace_scores

    async def execute(self, interaction_id: uuid.UUID) -> LiveInteractionDetail:
        interaction = await self._live.get_by_id(interaction_id)
        if interaction is None:
            raise LiveInteractionNotFoundError(interaction_id)
        scores = await self._live.list_scores(interaction_id)
        score_reviews = await self._live.list_score_reviews_by_score_ids([s.id for s in scores])
        trace_scores: list[TraceScore] = []
        trace_id = source_trace_id(interaction)
        if self._trace_scores is not None and trace_id is not None:
            found = await self._trace_scores.list_by_trace_ids(interaction.project_id, [trace_id])
            trace_scores = found.get(trace_id, [])
        return LiveInteractionDetail(
            interaction=interaction,
            scores=scores,
            score_reviews=score_reviews,
            trace_scores=trace_scores,
        )


class UpsertLiveScoreReview:
    def __init__(self, live: LiveInteractionRepository) -> None:
        self._live = live

    async def execute(self, command: UpsertLiveScoreReviewCommand) -> LiveScoreReview:
        score = await self._live.get_score(command.score_id)
        if score is None:
            raise LiveScoreNotFoundError(command.score_id)
        review = LiveScoreReview.create(
            command.score_id,
            command.verdict,
            corrected_explanation=command.corrected_explanation,
            note=command.note,
            reviewer=command.reviewer,
        )
        return await self._live.upsert_score_review(review)


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
    from opengrade_server.application.evaluators import CreateEvaluator
    from opengrade_server.application.metrics_sets import EnsureProjectDefaultMetricsSet
    from opengrade_server.infrastructure.db import try_get_session_factory
    from opengrade_server.infrastructure.repositories import (
        SqlAlchemyEvaluatorRepository,
        SqlAlchemyLiveInteractionRepository,
        SqlAlchemyMetricsSetRepository,
        SqlAlchemyProjectRepository,
    )

    factory = try_get_session_factory()
    if factory is None:
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
