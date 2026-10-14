from __future__ import annotations

import uuid

from aiobs_server.application.live_interactions import GetLiveInteraction, ListLiveInteractions
from aiobs_server.domain.live_interaction import LiveInteraction, LiveInteractionScore
from aiobs_server.domain.trace_score import TraceScore
from support.repositories import InMemoryTraceScoreRepository
from test_api_live_interactions import InMemoryLiveRepository

PROJECT = uuid.uuid4()


async def _interaction(
    live: InMemoryLiveRepository, question: str, trace_id: str | None
) -> LiveInteraction:
    metadata = {"source_trace_id": trace_id} if trace_id else {}
    interaction = LiveInteraction.create(PROJECT, question, "answer", metadata=metadata)
    return await live.add(interaction)


async def test_list_joins_trace_scores_with_one_query_per_page() -> None:
    live, scores = InMemoryLiveRepository(), InMemoryTraceScoreRepository()
    a = await _interaction(live, "qa", "aa" * 16)
    b = await _interaction(live, "qb", "bb" * 16)
    c = await _interaction(live, "qc", None)
    await scores.upsert_many(
        [
            TraceScore.create(PROJECT, "aa" * 16, "quality", value=1.0, label="PASS"),
            TraceScore.create(PROJECT, "aa" * 16, "user_feedback", value=1.0, source="human"),
        ]
    )

    result = await ListLiveInteractions(live, scores).execute(PROJECT)

    assert {i[0].id for i in result.items} == {a.id, b.id, c.id}
    assert [s.name for s in result.trace_scores[a.id]] == ["quality", "user_feedback"]
    assert b.id not in result.trace_scores and c.id not in result.trace_scores
    assert scores.list_calls == 1


async def test_failed_only_counts_trace_score_fails() -> None:
    live, scores = InMemoryLiveRepository(), InMemoryTraceScoreRepository()
    judged_fail = await _interaction(live, "judge fail", "aa" * 16)
    await live.replace_scores(
        judged_fail.id,
        [LiveInteractionScore.create(judged_fail.id, "groundedness", score=0.1, threshold=0.7)],
    )
    thumbs_down = await _interaction(live, "thumbs down", "bb" * 16)
    sdk_fail = await _interaction(live, "sdk fail", "cc" * 16)
    await _interaction(live, "fine", "dd" * 16)
    await scores.upsert_many(
        [
            TraceScore.create(
                PROJECT, "bb" * 16, "user_feedback", value=0.0, source="human", label="FAIL"
            ),
            TraceScore.create(PROJECT, "cc" * 16, "cited", value=0.0, label="FAIL"),
            TraceScore.create(PROJECT, "dd" * 16, "cited", value=1.0, label="PASS"),
        ]
    )

    result = await ListLiveInteractions(live, scores).execute(PROJECT, failed_only=True)

    assert {i[0].id for i in result.items} == {judged_fail.id, thumbs_down.id, sdk_fail.id}


async def test_list_without_trace_score_repository_is_unchanged() -> None:
    live = InMemoryLiveRepository()
    await _interaction(live, "q", "aa" * 16)
    result = await ListLiveInteractions(live).execute(PROJECT)
    assert len(result.items) == 1 and result.trace_scores == {}


async def test_detail_joins_trace_scores() -> None:
    live, scores = InMemoryLiveRepository(), InMemoryTraceScoreRepository()
    a = await _interaction(live, "qa", "AA" * 16)  # stored ids may be upper-case
    await scores.upsert_many([TraceScore.create(PROJECT, "aa" * 16, "quality", value=1.0)])

    detail = await GetLiveInteraction(live, scores).execute(a.id)

    assert [s.name for s in detail.trace_scores] == ["quality"]
