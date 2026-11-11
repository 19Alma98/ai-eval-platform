from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from opengrade_server.domain.conversation import (
    Conversation,
    ConversationScore,
    ConversationSummary,
)
from opengrade_server.infrastructure.models import (
    ConversationModel,
    ConversationScoreModel,
    SpanModel,
    TraceModel,
)

_EXPERIMENT_ID_ATTR = "opengrade.experiment_id"


def _experiment_bound_trace_exists() -> Any:
    return exists().where(
        SpanModel.trace_pk == TraceModel.id,
        SpanModel.attributes[_EXPERIMENT_ID_ATTR].as_string().is_not(None),
        SpanModel.attributes[_EXPERIMENT_ID_ATTR].as_string() != "",
    )


def _to_domain(row: ConversationModel) -> Conversation:
    return Conversation(
        id=row.id,
        project_id=row.project_id,
        session_id=row.session_id,
        user_id=row.user_id,
        environment=row.environment,
        turn_count=row.turn_count,
        started_at=row.started_at,
        last_activity_at=row.last_activity_at,
        judge_status=row.judge_status,
        metrics_set_id=row.metrics_set_id,
        score_warning=row.score_warning,
        error_message=row.error_message,
        created_at=row.created_at,
        scored_at=row.scored_at,
        metadata=dict(row.metadata_json or {}),
    )


def _score_to_domain(row: ConversationScoreModel) -> ConversationScore:
    return ConversationScore(
        id=row.id,
        conversation_id=row.conversation_id,
        evaluator_id=row.evaluator_id,
        kind=row.kind,
        score=row.score,
        label=row.label,
        explanation=row.explanation,
        threshold=row.threshold,
        metadata=dict(row.metadata_json or {}),
        created_at=row.created_at,
    )


class SqlAlchemyConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, conversation_id: uuid.UUID) -> Conversation | None:
        row = await self._session.get(ConversationModel, conversation_id)
        return _to_domain(row) if row else None

    async def get_by_session(self, project_id: uuid.UUID, session_id: str) -> Conversation | None:
        result = await self._session.execute(
            select(ConversationModel).where(
                ConversationModel.project_id == project_id,
                ConversationModel.session_id == session_id,
            )
        )
        row = result.scalar_one_or_none()
        return _to_domain(row) if row else None

    async def upsert(self, conversation: Conversation) -> Conversation:
        existing = await self.get_by_session(conversation.project_id, conversation.session_id)
        if existing is None:
            row = ConversationModel(
                id=conversation.id,
                project_id=conversation.project_id,
                session_id=conversation.session_id,
                user_id=conversation.user_id,
                environment=conversation.environment,
                turn_count=conversation.turn_count,
                started_at=conversation.started_at,
                last_activity_at=conversation.last_activity_at,
                judge_status=conversation.judge_status,
                metrics_set_id=conversation.metrics_set_id,
                score_warning=conversation.score_warning,
                error_message=conversation.error_message,
                metadata_json=dict(conversation.metadata),
                created_at=conversation.created_at,
                scored_at=conversation.scored_at,
            )
            self._session.add(row)
        else:
            loaded = await self._session.get(ConversationModel, existing.id)
            assert loaded is not None
            row = loaded
            row.user_id = conversation.user_id
            row.environment = conversation.environment
            row.turn_count = conversation.turn_count
            row.started_at = conversation.started_at
            row.last_activity_at = conversation.last_activity_at
            row.judge_status = conversation.judge_status
            row.metrics_set_id = conversation.metrics_set_id
            row.score_warning = conversation.score_warning
            row.error_message = conversation.error_message
            row.metadata_json = dict(conversation.metadata)
            row.scored_at = conversation.scored_at
            conversation = (
                conversation
                if conversation.id == existing.id
                else Conversation(
                    id=existing.id,
                    project_id=conversation.project_id,
                    session_id=conversation.session_id,
                    user_id=conversation.user_id,
                    environment=conversation.environment,
                    turn_count=conversation.turn_count,
                    started_at=conversation.started_at,
                    last_activity_at=conversation.last_activity_at,
                    judge_status=conversation.judge_status,
                    metrics_set_id=conversation.metrics_set_id,
                    score_warning=conversation.score_warning,
                    error_message=conversation.error_message,
                    created_at=existing.created_at,
                    scored_at=conversation.scored_at,
                    metadata=dict(conversation.metadata),
                )
            )
        await self._session.commit()
        return (
            conversation
            if existing is None
            else (
                await self.get_by_session(conversation.project_id, conversation.session_id)
                or conversation
            )
        )

    async def update(self, conversation: Conversation) -> Conversation:
        row = await self._session.get(ConversationModel, conversation.id)
        if row is None:
            raise ValueError(f"Conversation not found: {conversation.id}")
        row.user_id = conversation.user_id
        row.environment = conversation.environment
        row.turn_count = conversation.turn_count
        row.started_at = conversation.started_at
        row.last_activity_at = conversation.last_activity_at
        row.judge_status = conversation.judge_status
        row.metrics_set_id = conversation.metrics_set_id
        row.score_warning = conversation.score_warning
        row.error_message = conversation.error_message
        row.metadata_json = dict(conversation.metadata)
        row.scored_at = conversation.scored_at
        await self._session.commit()
        return conversation

    async def replace_scores(
        self, conversation_id: uuid.UUID, scores: list[ConversationScore]
    ) -> list[ConversationScore]:
        existing = await self._session.execute(
            select(ConversationScoreModel).where(
                ConversationScoreModel.conversation_id == conversation_id
            )
        )
        for row in existing.scalars().all():
            await self._session.delete(row)
        await self._session.flush()
        saved: list[ConversationScore] = []
        for score in scores:
            row = ConversationScoreModel(
                id=score.id,
                conversation_id=score.conversation_id,
                evaluator_id=score.evaluator_id,
                kind=score.kind,
                score=score.score,
                label=score.label,
                explanation=score.explanation,
                threshold=score.threshold,
                created_at=score.created_at,
                metadata_json=dict(score.metadata),
            )
            self._session.add(row)
            saved.append(score)
        await self._session.commit()
        return saved

    async def list_scores(self, conversation_id: uuid.UUID) -> list[ConversationScore]:
        result = await self._session.execute(
            select(ConversationScoreModel)
            .where(ConversationScoreModel.conversation_id == conversation_id)
            .order_by(ConversationScoreModel.created_at.asc())
        )
        return [_score_to_domain(row) for row in result.scalars().all()]

    async def list_idle(
        self,
        *,
        idle_before: datetime,
        statuses: frozenset[str] | set[str],
        limit: int = 100,
    ) -> list[Conversation]:
        if not statuses:
            return []
        result = await self._session.execute(
            select(ConversationModel)
            .where(
                ConversationModel.judge_status.in_(tuple(statuses)),
                ConversationModel.last_activity_at < idle_before,
            )
            .order_by(ConversationModel.last_activity_at.asc())
            .limit(max(1, min(limit, 500)))
        )
        return [_to_domain(row) for row in result.scalars().all()]

    async def list_summaries(
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
        stmt = (
            select(
                TraceModel.session_id,
                func.min(TraceModel.start_time).label("started_at"),
                func.max(TraceModel.start_time).label("last_activity_at"),
                func.count().label("turn_count"),
                func.max(TraceModel.user_id).label("user_id"),
                func.max(TraceModel.environment).label("environment"),
            )
            .where(
                TraceModel.project_id == project_id,
                TraceModel.session_id.is_not(None),
                TraceModel.session_id != "",
                ~_experiment_bound_trace_exists(),
            )
            .group_by(TraceModel.session_id)
        )
        if since is not None:
            stmt = stmt.having(func.max(TraceModel.start_time) >= since)
        if until is not None:
            stmt = stmt.having(func.max(TraceModel.start_time) < until)
        if user_id is not None:
            stmt = stmt.having(func.max(TraceModel.user_id) == user_id)
        if environment is not None:
            stmt = stmt.having(func.max(TraceModel.environment) == environment)
        if search:
            stmt = stmt.where(TraceModel.session_id.ilike(f"%{search.strip()}%"))
        stmt = (
            stmt.order_by(func.max(TraceModel.start_time).desc())
            .offset(max(0, offset))
            .limit(max(1, min(limit, 200)))
        )
        result = await self._session.execute(stmt)
        rows = result.all()
        session_ids = [r.session_id for r in rows if r.session_id]
        persisted: dict[str, ConversationModel] = {}
        if session_ids:
            conv_result = await self._session.execute(
                select(ConversationModel)
                .where(
                    ConversationModel.project_id == project_id,
                    ConversationModel.session_id.in_(session_ids),
                )
                .options(selectinload(ConversationModel.scores))
            )
            for persisted_row in conv_result.scalars().unique().all():
                persisted[persisted_row.session_id] = persisted_row

        out: list[ConversationSummary] = []
        for row in rows:
            conv = persisted.get(row.session_id)
            failing: list[str] = []
            if conv is not None:
                for score in conv.scores:
                    label = (score.label or "").upper()
                    if label == "FAIL" or (
                        score.threshold is not None
                        and score.score is not None
                        and score.score < score.threshold
                        and label not in {"PASS", "SKIPPED", "ERROR"}
                    ):
                        failing.append(score.kind)
            out.append(
                ConversationSummary(
                    session_id=row.session_id,
                    user_id=row.user_id,
                    environment=row.environment,
                    turn_count=int(row.turn_count or 0),
                    started_at=row.started_at,
                    last_activity_at=row.last_activity_at,
                    conversation_id=conv.id if conv else None,
                    judge_status=conv.judge_status if conv else None,
                    failing_score_kinds=tuple(failing),
                )
            )
        return out
