from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from opengrade_server.application.conversations import (
    ConversationDetail,
    ConversationSummary,
    ConversationTurn,
    ScoreConversation,
    enabled_conversation_judge_entries,
    session_judges_enabled,
)
from opengrade_server.domain.conversation import Conversation
from opengrade_server.domain.metrics_set import MetricsSet


def test_session_judges_enabled_false_on_default_set() -> None:
    ms = MetricsSet.create_project_default(uuid.uuid4())
    assert session_judges_enabled(ms) is False
    assert enabled_conversation_judge_entries(ms) == []


def test_session_judges_enabled_true_when_one_conversation_judge_active() -> None:
    ms = MetricsSet.create_project_default(uuid.uuid4())
    entries = tuple(replace(e, enabled=True) if e.kind == "resolution" else e for e in ms.entries)
    ms = replace(ms, entries=entries)
    assert session_judges_enabled(ms) is True
    assert [e.kind for e in enabled_conversation_judge_entries(ms)] == ["resolution"]


@pytest.mark.asyncio
async def test_score_conversation_noop_when_judges_disabled() -> None:
    project_id = uuid.uuid4()
    session_id = "sess-noop"
    now = datetime.now(UTC)
    conv = Conversation.create(
        project_id,
        session_id,
        turn_count=1,
        started_at=now,
        last_activity_at=now,
    )
    detail = ConversationDetail(
        summary=ConversationSummary(
            session_id=session_id,
            user_id=None,
            environment=None,
            turn_count=1,
            started_at=now,
            last_activity_at=now,
            conversation_id=conv.id,
            judge_status="open",
            failing_score_kinds=(),
        ),
        conversation=conv,
        turns=[
            ConversationTurn(
                trace_id="t1",
                start_time=now,
                question="hi",
                answer="hello",
                user_id=None,
                live_interaction_id=None,
                search_query=None,
            )
        ],
        scores=[],
        live_interactions=[],
    )
    metrics_set = MetricsSet.create_project_default(project_id)
    conversations = AsyncMock()
    ensure = AsyncMock()
    ensure.execute = AsyncMock(return_value=metrics_set)

    scorer = ScoreConversation(
        conversations,
        AsyncMock(),
        AsyncMock(),
        ensure,
        AsyncMock(),
        AsyncMock(),
        AsyncMock(),
    )
    scorer._get = AsyncMock()
    scorer._get.execute = AsyncMock(return_value=detail)

    result = await scorer.execute(project_id, session_id)

    assert result is detail
    assert result.conversation is not None
    assert result.conversation.judge_status == "open"
    assert result.scores == []
    conversations.update.assert_not_called()
    conversations.replace_scores.assert_not_called()
    conversations.upsert.assert_not_called()
