from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from opengrade_server.application.live_interactions import ListLiveInteractions
from opengrade_server.application.monitoring import (
    GetProductionMonitoring,
    histogram,
    percentile,
)
from opengrade_server.application.projects import ProjectNotFoundError
from opengrade_server.domain.live_interaction import (
    LiveInteraction,
    LiveInteractionScore,
    LiveScoreReview,
)
from opengrade_server.domain.live_overview import LiveInRangeResult, LiveInteractionInRange
from opengrade_server.domain.project import Project
from opengrade_server.domain.trace import Span, Trace
from opengrade_server.domain.trace_score import TraceScore
from tests.support.repositories import InMemoryTraceScoreRepository
from tests.test_api_live_interactions import InMemoryLiveRepository, InMemoryProjectRepository

SINCE = datetime(2026, 1, 1, tzinfo=UTC)
UNTIL = SINCE + timedelta(hours=1)  # 5-minute buckets


def test_percentile_interpolates() -> None:
    assert percentile([], 50) is None
    assert percentile([7.0], 99) == 7.0
    assert percentile([1.0, 2.0, 3.0, 4.0], 50) == 2.5
    assert percentile([10.0, 20.0, 30.0], 100) == 30.0


def test_histogram_uses_unit_range_for_scores() -> None:
    edges, counts = histogram([0.0, 0.05, 0.95, 1.0])
    assert edges[0] == 0.0 and edges[-1] == 1.0
    assert counts[0] == 2 and counts[-1] == 2 and sum(counts) == 4
    edges, counts = histogram([2.0, 4.0], bins=2)
    assert edges == [2.0, 3.0, 4.0] and counts == [1, 1]
    assert histogram([]) == ([], [])


class _Traces:
    def __init__(self, traces: list[Trace]) -> None:
        self._traces = traces

    async def list_with_spans_in_range(
        self, project_id: uuid.UUID, *, since: datetime, until: datetime, limit: int = 5000
    ) -> list[Trace]:
        rows = [t for t in self._traces if since <= t.start_time <= until]
        return rows[:limit]


class _Live(InMemoryLiveRepository):
    async def list_in_range(
        self, project_id: uuid.UUID, *, since: datetime, until: datetime, limit: int = 10_000
    ) -> LiveInRangeResult:
        items = [
            LiveInteractionInRange(interaction=i, scores=await self.list_scores(i.id))
            for i in self._items.values()
            if i.project_id == project_id and since <= i.created_at <= until
        ]
        return LiveInRangeResult(items=items, truncated=False)


def _trace(project_id: uuid.UUID, offset_min: int, *, ms: int, error: bool = False) -> Trace:
    start = SINCE + timedelta(minutes=offset_min)
    end = start + timedelta(milliseconds=ms)
    llm = Span(
        id=uuid.uuid4(),
        span_id=uuid.uuid4().hex[:16],
        parent_span_id=None,
        name="llm",
        kind="LLM",
        start_time=start,
        end_time=end,
        status="error" if error else "ok",
        attributes={
            "gen_ai.usage.input_tokens": 100,
            "gen_ai.usage.output_tokens": 20,
            "gen_ai.usage.cost": 0.01,
        },
    )
    return Trace(
        id=uuid.uuid4(),
        project_id=project_id,
        trace_id=uuid.uuid4().hex,
        name="answer",
        status="error" if error else "ok",
        start_time=start,
        end_time=end,
        spans=(llm,),
    )


async def _interaction(
    live: _Live, project_id: uuid.UUID, offset_min: int, score: float
) -> LiveInteractionScore:
    interaction = replace(
        LiveInteraction.create(project_id, "q?", "a."),
        created_at=SINCE + timedelta(minutes=offset_min),
        judge_status="scored",
    )
    await live.add(interaction)
    row = LiveInteractionScore.create(interaction.id, "groundedness", score=score, threshold=0.7)
    await live.replace_scores(interaction.id, [row])
    return row


async def test_monitoring_aggregates_traffic_and_scores() -> None:
    projects = InMemoryProjectRepository()
    project = await projects.add(Project.create("Mon", slug="mon"))
    traces = [
        _trace(project.id, 1, ms=100),
        _trace(project.id, 2, ms=300),
        _trace(project.id, 12, ms=500, error=True),
        _trace(project.id, 90, ms=900),  # outside the window
    ]
    live = _Live()
    reviewed = await _interaction(live, project.id, 3, 0.9)
    await _interaction(live, project.id, 14, 0.2)
    await live.upsert_score_review(LiveScoreReview.create(reviewed.id, "agree"))
    scores = InMemoryTraceScoreRepository()
    await scores.upsert_many(
        [TraceScore.create(project.id, traces[0].trace_id, "user_feedback", value=0.0)]
    )

    result = await GetProductionMonitoring(projects, _Traces(traces), live, scores).execute(
        project.id, since=SINCE, until=UNTIL
    )

    assert result.n_traces == 3
    assert result.n_errors == 1
    assert result.latency.p50_ms == pytest.approx(300.0)
    assert result.total_tokens == pytest.approx(360.0)
    assert result.cost_usd == pytest.approx(0.03)
    assert result.bucket_seconds == 300
    assert len(result.traffic) == 12
    assert [b.n_traces for b in result.traffic[:3]] == [2, 0, 1]
    assert result.traffic[2].n_errors == 1
    assert result.n_needs_review == 1

    by_name = {(m.name, m.source): m for m in result.metrics}
    judge = by_name[("groundedness", "judge")]
    assert judge.n == 2
    assert judge.fail_rate == pytest.approx(0.5)
    assert judge.threshold == 0.7
    assert sum(judge.histogram_counts) == 2
    assert [b.n for b in judge.series[:3]] == [1, 0, 1]
    feedback = by_name[("user_feedback", "sdk")]
    assert feedback.n == 1 and feedback.mean == 0.0


def _experiment_bound_trace(project_id: uuid.UUID, offset_min: int, *, ms: int) -> Trace:
    start = SINCE + timedelta(minutes=offset_min)
    end = start + timedelta(milliseconds=ms)
    chain = Span(
        id=uuid.uuid4(),
        span_id=uuid.uuid4().hex[:16],
        parent_span_id=None,
        name="opengrade.eval demo",
        kind="CHAIN",
        start_time=start,
        end_time=end,
        status="ok",
        attributes={
            "opengrade.experiment_id": str(uuid.uuid4()),
            "opengrade.dataset_item_id": str(uuid.uuid4()),
            "gen_ai.usage.input_tokens": 50,
            "gen_ai.usage.output_tokens": 10,
            "gen_ai.usage.cost": 0.005,
        },
    )
    return Trace(
        id=uuid.uuid4(),
        project_id=project_id,
        trace_id=uuid.uuid4().hex,
        name="opengrade.eval demo",
        status="ok",
        start_time=start,
        end_time=end,
        spans=(chain,),
    )


async def test_monitoring_excludes_experiment_bound_traces() -> None:
    projects = InMemoryProjectRepository()
    project = await projects.add(Project.create("MonEval", slug="mon-eval"))
    production = [
        _trace(project.id, 1, ms=100),
        _trace(project.id, 2, ms=300, error=True),
    ]
    offline = [
        _experiment_bound_trace(project.id, 3, ms=200),
        _experiment_bound_trace(project.id, 4, ms=400),
    ]
    live = _Live()
    scores = InMemoryTraceScoreRepository()

    result = await GetProductionMonitoring(
        projects, _Traces(production + offline), live, scores
    ).execute(project.id, since=SINCE, until=UNTIL)

    assert result.n_traces == 2
    assert result.n_errors == 1
    assert result.latency.p50_ms == pytest.approx(200.0)
    assert result.total_tokens == pytest.approx(240.0)
    assert result.cost_usd == pytest.approx(0.02)


async def test_monitoring_unknown_project() -> None:
    use_case = GetProductionMonitoring(
        InMemoryProjectRepository(), _Traces([]), _Live(), InMemoryTraceScoreRepository()
    )
    with pytest.raises(ProjectNotFoundError):
        await use_case.execute(uuid.uuid4(), since=SINCE, until=UNTIL)


async def test_list_unreviewed_only_is_the_annotation_queue() -> None:
    project_id = uuid.uuid4()
    live = _Live()
    reviewed = await _interaction(live, project_id, 1, 0.9)
    pending = await _interaction(live, project_id, 2, 0.3)
    await live.add(LiveInteraction.create(project_id, "not judged", "yet"))
    await live.upsert_score_review(LiveScoreReview.create(reviewed.id, "disagree"))

    projects = InMemoryProjectRepository()
    await projects.add(Project(id=project_id, name="P", slug="p", created_at=datetime.now(UTC)))
    result = await ListLiveInteractions(live, projects).execute(project_id, unreviewed_only=True)

    assert [item.id for item, _, _ in result.items] == [pending.live_interaction_id]
