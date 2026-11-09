from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from opengrade_server.application.datasets import (
    AddDatasetItem,
    AddDatasetItemCommand,
    DatasetNotFoundError,
)
from opengrade_server.application.evaluators import CreateEvaluator
from opengrade_server.application.metrics_sets import (
    EnsureProjectDefaultMetricsSet,
    find_or_create_evaluator_for_entry,
)
from opengrade_server.application.projects import ProjectNotFoundError
from opengrade_server.domain.conversation import (
    Conversation,
    ConversationScore,
    ConversationSummary,
)
from opengrade_server.domain.dataset import DatasetItem
from opengrade_server.domain.live_interaction import LiveInteraction
from opengrade_server.domain.rag_input import build_chat_input
from opengrade_server.domain.repositories import (
    DatasetRepository,
    EvaluatorRepository,
    LiveInteractionRepository,
    ProjectRepository,
    TraceRepository,
)
from opengrade_server.domain.trace import Trace
from opengrade_server.evaluation.outcomes import item_verdict
from opengrade_server.evaluation.protocol import EvaluationSample
from opengrade_server.evaluation.registry import create_evaluator
from opengrade_server.infrastructure.conversation_repository import SqlAlchemyConversationRepository
from opengrade_server.tracing.live_binding import answer_from_output, question_from_input

logger = logging.getLogger(__name__)

CONVERSATION_JUDGE_KINDS = frozenset(
    {"query_rewrite_faithfulness", "conversation_consistency", "resolution"}
)


@dataclass(frozen=True, slots=True)
class ConversationTurn:
    trace_id: str
    start_time: datetime
    question: str | None
    answer: str | None
    user_id: str | None
    live_interaction_id: uuid.UUID | None
    search_query: str | None


@dataclass(frozen=True, slots=True)
class ConversationDetail:
    summary: ConversationSummary
    conversation: Conversation | None
    turns: list[ConversationTurn]
    scores: list[ConversationScore]
    live_interactions: list[LiveInteraction]


class ConversationNotFoundError(Exception):
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        super().__init__(f"Conversation not found: {session_id}")


def _turn_from_trace(trace: Trace, live_id: uuid.UUID | None) -> ConversationTurn:
    question = question_from_input(trace.input)
    answer = answer_from_output(trace.output)
    search_query = None
    if isinstance(trace.metadata, dict):
        raw = trace.metadata.get("search_query")
        if isinstance(raw, str) and raw.strip():
            search_query = raw.strip()
    from opengrade_server.evaluation.trace_context import build_eval_context_from_trace

    ctx = build_eval_context_from_trace(trace)
    ctx_q = ctx.get("search_query")
    if isinstance(ctx_q, str) and ctx_q.strip():
        search_query = ctx_q.strip()
    return ConversationTurn(
        trace_id=trace.trace_id,
        start_time=trace.start_time,
        question=question,
        answer=answer,
        user_id=trace.user_id,
        live_interaction_id=live_id,
        search_query=search_query,
    )


class ListConversations:
    def __init__(
        self,
        projects: ProjectRepository,
        conversations: SqlAlchemyConversationRepository,
    ) -> None:
        self._projects = projects
        self._conversations = conversations

    async def execute(
        self,
        project_id: uuid.UUID,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        user_id: str | None = None,
        environment: str | None = None,
        search: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ConversationSummary]:
        if await self._projects.get_by_id(project_id) is None:
            raise ProjectNotFoundError(project_id)
        return await self._conversations.list_summaries(
            project_id,
            since=since,
            until=until,
            user_id=user_id,
            environment=environment,
            search=search,
            limit=limit,
            offset=offset,
        )


class GetConversation:
    def __init__(
        self,
        projects: ProjectRepository,
        conversations: SqlAlchemyConversationRepository,
        traces: TraceRepository,
        live: LiveInteractionRepository,
    ) -> None:
        self._projects = projects
        self._conversations = conversations
        self._traces = traces
        self._live = live

    async def execute(self, project_id: uuid.UUID, session_id: str) -> ConversationDetail:
        if await self._projects.get_by_id(project_id) is None:
            raise ProjectNotFoundError(project_id)
        traces = await self._traces.list_by_project(project_id, session_id=session_id, limit=200)
        if not traces:
            raise ConversationNotFoundError(session_id)
        traces = sorted(traces, key=lambda t: t.start_time)
        external_ids = [f"trace:{t.trace_id}" for t in traces]
        live_ids = await self._live.ids_by_external_ids(project_id, external_ids)
        turns = [_turn_from_trace(t, live_ids.get(f"trace:{t.trace_id}")) for t in traces]
        conversation = await self._conversations.get_by_session(project_id, session_id)
        scores = await self._conversations.list_scores(conversation.id) if conversation else []
        live_rows: list[LiveInteraction] = []
        for lid in live_ids.values():
            row = await self._live.get_by_id(lid)
            if row is not None:
                live_rows.append(row)
        summary = ConversationSummary(
            session_id=session_id,
            user_id=next((t.user_id for t in traces if t.user_id), None),
            environment=next((t.environment for t in traces if t.environment), None),
            turn_count=len(traces),
            started_at=traces[0].start_time,
            last_activity_at=traces[-1].start_time,
            conversation_id=conversation.id if conversation else None,
            judge_status=conversation.judge_status if conversation else None,
            failing_score_kinds=tuple(
                s.kind for s in scores if item_verdict(s.score, s.label, s.threshold) == "FAIL"
            ),
        )
        return ConversationDetail(
            summary=summary,
            conversation=conversation,
            turns=turns,
            scores=scores,
            live_interactions=live_rows,
        )


class SyncConversationActivity:
    """Upsert an open conversation row from the latest session activity."""

    def __init__(self, conversations: SqlAlchemyConversationRepository) -> None:
        self._conversations = conversations

    async def execute(
        self,
        project_id: uuid.UUID,
        session_id: str,
        *,
        user_id: str | None,
        environment: str | None,
        turn_count: int,
        started_at: datetime,
        last_activity_at: datetime,
    ) -> Conversation:
        existing = await self._conversations.get_by_session(project_id, session_id)
        if existing is None:
            conv = Conversation.create(
                project_id,
                session_id,
                user_id=user_id,
                environment=environment,
                turn_count=turn_count,
                started_at=started_at,
                last_activity_at=last_activity_at,
            )
            return await self._conversations.upsert(conv)
        if existing.judge_status in {"scored", "running", "error"}:
            # New activity after scoring re-opens the conversation.
            if last_activity_at > existing.last_activity_at:
                updated = existing.with_activity(
                    turn_count=turn_count,
                    last_activity_at=last_activity_at,
                    user_id=user_id,
                    environment=environment,
                ).with_status("open")
                return await self._conversations.update(updated)
            return existing
        updated = existing.with_activity(
            turn_count=turn_count,
            last_activity_at=last_activity_at,
            user_id=user_id,
            environment=environment,
        )
        return await self._conversations.update(updated)


class ScoreConversation:
    def __init__(
        self,
        conversations: SqlAlchemyConversationRepository,
        traces: TraceRepository,
        live: LiveInteractionRepository,
        metrics_sets: EnsureProjectDefaultMetricsSet,
        evaluators: EvaluatorRepository,
        create_evaluator: CreateEvaluator,
        projects: ProjectRepository,
    ) -> None:
        self._conversations = conversations
        self._get = GetConversation(projects, conversations, traces, live)
        self._ensure_default = metrics_sets
        self._evaluators = evaluators
        self._create_evaluator = create_evaluator

    async def execute(self, project_id: uuid.UUID, session_id: str) -> ConversationDetail:
        detail = await self._get.execute(project_id, session_id)
        turns = detail.turns
        if not turns:
            raise ConversationNotFoundError(session_id)

        history: list[dict[str, str]] = []
        for turn in turns[:-1]:
            if turn.question:
                history.append({"role": "user", "content": turn.question})
            if turn.answer:
                history.append({"role": "assistant", "content": turn.answer})
        last = turns[-1]
        question = last.question or ""
        chat_input = build_chat_input(history=history, question=question or "(empty)")
        context: dict[str, Any] = {}
        if last.search_query:
            context["search_query"] = last.search_query
        # Prefer documents from the last live interaction when present.
        for live in detail.live_interactions:
            src = live.metadata.get("source_trace_id")
            if src == last.trace_id and live.documents:
                context["documents"] = list(live.documents)
                break

        sync = SyncConversationActivity(self._conversations)
        conversation = await sync.execute(
            project_id,
            session_id,
            user_id=detail.summary.user_id,
            environment=detail.summary.environment,
            turn_count=detail.summary.turn_count,
            started_at=detail.summary.started_at,
            last_activity_at=detail.summary.last_activity_at,
        )
        conversation = await self._conversations.update(conversation.with_status("running"))

        metrics_set = await self._ensure_default.execute(project_id)
        entries = [
            e for e in metrics_set.entries if e.enabled and e.kind in CONVERSATION_JUDGE_KINDS
        ]
        sample = EvaluationSample(
            input=chat_input,
            expected_output=None,
            actual_output=last.answer,
            context=context or None,
            metadata={},
        )
        scores: list[ConversationScore] = []
        for entry in entries:
            entity = await find_or_create_evaluator_for_entry(
                self._evaluators,
                self._create_evaluator,
                project_id,
                entry,
            )
            kind = str(entity.config.get("kind", entry.kind)).strip()
            config = {**entity.config, **entry.config, "kind": kind}
            evaluator = create_evaluator(kind, config)
            result = await evaluator.evaluate(sample)
            verdict = item_verdict(result.score, result.label, entry.threshold)
            scores.append(
                ConversationScore.create(
                    conversation.id,
                    kind=entry.kind,
                    evaluator_id=entity.id,
                    score=result.score,
                    label=verdict if verdict is not None else result.label,
                    explanation=result.explanation,
                    threshold=entry.threshold,
                    metadata=dict(result.metadata),
                )
            )
        await self._conversations.replace_scores(conversation.id, scores)
        await self._conversations.update(
            conversation.with_status(
                "scored",
                metrics_set_id=metrics_set.id,
                scored_at=datetime.now(UTC),
                error_message=None,
            )
        )
        return await self._get.execute(project_id, session_id)


@dataclass(frozen=True, slots=True)
class PromoteConversationCommand:
    project_id: uuid.UUID
    session_id: str
    dataset_id: uuid.UUID
    expected_output: str
    expected_doc_ids: list[str] | None = None
    mode: str = "full"  # full | last_turn


class PromoteConversation:
    def __init__(
        self,
        get_conversation: GetConversation,
        datasets: DatasetRepository,
        add_item: AddDatasetItem,
    ) -> None:
        self._get = get_conversation
        self._datasets = datasets
        self._add_item = add_item

    async def execute(self, command: PromoteConversationCommand) -> DatasetItem:
        detail = await self._get.execute(command.project_id, command.session_id)
        dataset = await self._datasets.get_by_id(command.dataset_id)
        if dataset is None:
            raise DatasetNotFoundError(command.dataset_id)
        if dataset.project_id != command.project_id:
            raise DatasetNotFoundError(command.dataset_id)

        turns = detail.turns
        if not turns:
            raise ConversationNotFoundError(command.session_id)
        last = turns[-1]
        if command.mode == "last_turn":
            history: list[dict[str, str]] = []
            for turn in turns[:-1]:
                if turn.question:
                    history.append({"role": "user", "content": turn.question})
                if turn.answer:
                    history.append({"role": "assistant", "content": turn.answer})
        else:
            history = []
            for turn in turns[:-1]:
                if turn.question:
                    history.append({"role": "user", "content": turn.question})
                if turn.answer:
                    history.append({"role": "assistant", "content": turn.answer})
        question = last.question or ""
        item_input: Any
        if dataset.task_type == "rag_chat":
            item_input = build_chat_input(history=history, question=question or "(empty)")
        else:
            item_input = question
        metadata: dict[str, Any] = {}
        if command.expected_doc_ids:
            metadata["expected_doc_ids"] = list(command.expected_doc_ids)
        return await self._add_item.execute(
            AddDatasetItemCommand(
                dataset_id=command.dataset_id,
                input=item_input,
                expected_output=command.expected_output,
                actual_output=last.answer,
                metadata=metadata or None,
                source_trace_id=last.trace_id,
            )
        )


async def score_idle_conversations(
    *,
    idle_minutes: float = 15.0,
    sample_rate: float = 1.0,
    limit: int = 20,
) -> int:
    """Score open conversations that have been idle; returns how many were scored."""
    from opengrade_server.application.evaluators import CreateEvaluator
    from opengrade_server.application.metrics_sets import EnsureProjectDefaultMetricsSet
    from opengrade_server.infrastructure.db import try_get_session_factory
    from opengrade_server.infrastructure.repositories import (
        SqlAlchemyEvaluatorRepository,
        SqlAlchemyLiveInteractionRepository,
        SqlAlchemyMetricsSetRepository,
        SqlAlchemyProjectRepository,
        SqlAlchemyTraceRepository,
    )

    factory = try_get_session_factory()
    if factory is None:
        return 0
    idle_before = datetime.now(UTC) - timedelta(minutes=idle_minutes)
    scored = 0
    async with factory() as session:
        conversations = SqlAlchemyConversationRepository(session)
        projects = SqlAlchemyProjectRepository(session)
        traces = SqlAlchemyTraceRepository(session)
        live = SqlAlchemyLiveInteractionRepository(session)
        metrics = SqlAlchemyMetricsSetRepository(session)
        evaluators = SqlAlchemyEvaluatorRepository(session)
        create_eval = CreateEvaluator(evaluators, projects)
        ensure = EnsureProjectDefaultMetricsSet(metrics, evaluators, projects, create_eval)
        scorer = ScoreConversation(
            conversations, traces, live, ensure, evaluators, create_eval, projects
        )
        idle = await conversations.list_idle(
            idle_before=idle_before, statuses={"open", "pending"}, limit=limit
        )
        for conv in idle:
            # Deterministic sample by session id hash.
            if sample_rate < 1.0:
                bucket = (hash(conv.session_id) % 10_000) / 10_000.0
                if bucket >= sample_rate:
                    await conversations.update(conv.with_status("unsampled"))
                    continue
            try:
                await scorer.execute(conv.project_id, conv.session_id)
                scored += 1
            except Exception:  # noqa: BLE001
                logger.exception("Conversation scoring failed for session %s", conv.session_id)
                await conversations.update(
                    conv.with_status(
                        "error",
                        error_message="scoring failed",
                        scored_at=datetime.now(UTC),
                    )
                )
    return scored


async def run_conversation_score_loop(
    interval_seconds: float, *, idle_minutes: float = 15.0
) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            await score_idle_conversations(idle_minutes=idle_minutes)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("Conversation idle scoring loop failed")


async def refresh_conversation_from_trace(
    conversations: SqlAlchemyConversationRepository,
    traces: TraceRepository,
    project_id: uuid.UUID,
    session_id: str,
) -> None:
    """Keep the open conversation projection in sync when a new trace arrives."""
    rows = await traces.list_by_project(project_id, session_id=session_id, limit=200)
    if not rows:
        return
    rows = sorted(rows, key=lambda t: t.start_time)
    await SyncConversationActivity(conversations).execute(
        project_id,
        session_id,
        user_id=next((t.user_id for t in rows if t.user_id), None),
        environment=next((t.environment for t in rows if t.environment), None),
        turn_count=len(rows),
        started_at=rows[0].start_time,
        last_activity_at=rows[-1].start_time,
    )
