"""Production monitoring: latency, tokens, cost and score time series over traces."""

from __future__ import annotations

import math
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from opengrade_server.application.live_interactions import score_is_failed
from opengrade_server.application.project_overview import bucket_size_for_range
from opengrade_server.application.projects import ProjectNotFoundError
from opengrade_server.domain.live_overview import LiveInteractionInRange
from opengrade_server.domain.repositories import (
    LiveInteractionRepository,
    ProjectRepository,
    TraceRepository,
    TraceScoreRepository,
)
from opengrade_server.domain.trace import Trace
from opengrade_server.domain.trace_score import trace_score_is_failed
from opengrade_server.evaluation.trace_context import build_eval_context_from_trace

TRACE_LIMIT = 5000
HISTOGRAM_BINS = 10
_TRACE_SCORE_CHUNK = 500
_REVIEW_CHUNK = 1000


@dataclass(frozen=True, slots=True)
class LatencyPercentiles:
    p50_ms: float | None
    p90_ms: float | None
    p99_ms: float | None


@dataclass(frozen=True, slots=True)
class TrafficBucket:
    bucket_start: datetime
    n_traces: int
    n_errors: int
    latency: LatencyPercentiles
    total_tokens: float
    cost_usd: float


@dataclass(frozen=True, slots=True)
class MetricBucket:
    bucket_start: datetime
    n: int
    mean: float | None
    fail_rate: float | None


@dataclass(frozen=True, slots=True)
class MetricMonitor:
    name: str
    source: str  # "judge" (live LLM judge) or the trace-score source ("sdk", "human", "judge")
    n: int
    mean: float | None
    fail_rate: float | None
    threshold: float | None
    histogram_edges: list[float]
    histogram_counts: list[int]
    series: list[MetricBucket]


@dataclass(frozen=True, slots=True)
class ProductionMonitoring:
    since: datetime
    until: datetime
    bucket_seconds: int
    n_traces: int
    n_errors: int
    latency: LatencyPercentiles
    prompt_tokens: float
    completion_tokens: float
    total_tokens: float
    cost_usd: float
    traces_truncated: bool
    n_needs_review: int
    traffic: list[TrafficBucket]
    metrics: list[MetricMonitor]


def percentile(values: list[float], q: float) -> float | None:
    """Linear-interpolated percentile (q in [0, 100]); None for no values."""
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * q / 100.0
    low = math.floor(rank)
    high = math.ceil(rank)
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


def latency_percentiles(values: list[float]) -> LatencyPercentiles:
    return LatencyPercentiles(
        p50_ms=percentile(values, 50),
        p90_ms=percentile(values, 90),
        p99_ms=percentile(values, 99),
    )


def histogram(values: list[float], bins: int = HISTOGRAM_BINS) -> tuple[list[float], list[int]]:
    """Equal-width bins over [0, 1] when every value fits there (judge scores), else min..max."""
    if not values:
        return [], []
    low, high = min(values), max(values)
    if low >= 0.0 and high <= 1.0:
        low, high = 0.0, 1.0
    if high == low:
        high = low + 1.0
    width = (high - low) / bins
    edges = [low + width * i for i in range(bins + 1)]
    counts = [0] * bins
    for value in values:
        idx = min(int((value - low) / width), bins - 1)
        counts[idx] += 1
    return edges, counts


_USAGE_KEYS = ("latency_ms", "prompt_tokens", "completion_tokens", "total_tokens", "cost_usd")


def _usage(trace: Trace) -> dict[str, float]:
    """Latency, token and cost figures recorded on a trace (absent keys were not recorded)."""
    context = build_eval_context_from_trace(trace)
    return {key: float(context[key]) for key in _USAGE_KEYS if key in context}


def _utc(ts: datetime) -> datetime:
    return ts if ts.tzinfo is not None else ts.replace(tzinfo=UTC)


@dataclass(slots=True)
class _Sample:
    at: datetime
    value: float | None
    failed: bool
    threshold: float | None


def _bucket_starts(since: datetime, until: datetime, bucket: timedelta) -> list[datetime]:
    starts: list[datetime] = []
    idx = 0
    while since + bucket * idx < until:
        starts.append(since + bucket * idx)
        idx += 1
    return starts


def _bucket_of(ts: datetime, since: datetime, bucket: timedelta, n_buckets: int) -> int | None:
    ts = _utc(ts)
    if ts < since:
        return None
    idx = int((ts - since) // bucket)
    return idx if idx < n_buckets else None


def _metric_monitor(
    name: str,
    source: str,
    samples: list[_Sample],
    *,
    since: datetime,
    bucket: timedelta,
    starts: list[datetime],
) -> MetricMonitor:
    values = [s.value for s in samples if s.value is not None]
    by_bucket: dict[int, list[_Sample]] = defaultdict(list)
    for sample in samples:
        idx = _bucket_of(sample.at, since, bucket, len(starts))
        if idx is not None:
            by_bucket[idx].append(sample)
    series: list[MetricBucket] = []
    for idx, start in enumerate(starts):
        rows = by_bucket.get(idx, [])
        scored = [r.value for r in rows if r.value is not None]
        series.append(
            MetricBucket(
                bucket_start=start,
                n=len(rows),
                mean=sum(scored) / len(scored) if scored else None,
                fail_rate=sum(1 for r in rows if r.failed) / len(rows) if rows else None,
            )
        )
    thresholds = [s.threshold for s in samples if s.threshold is not None]
    edges, counts = histogram(values)
    return MetricMonitor(
        name=name,
        source=source,
        n=len(samples),
        mean=sum(values) / len(values) if values else None,
        fail_rate=sum(1 for s in samples if s.failed) / len(samples) if samples else None,
        # Latest threshold wins: metrics sets change over time.
        threshold=thresholds[-1] if thresholds else None,
        histogram_edges=edges,
        histogram_counts=counts,
        series=series,
    )


class GetProductionMonitoring:
    def __init__(
        self,
        projects: ProjectRepository,
        traces: TraceRepository,
        live: LiveInteractionRepository,
        trace_scores: TraceScoreRepository,
    ) -> None:
        self._projects = projects
        self._traces = traces
        self._live = live
        self._trace_scores = trace_scores

    async def execute(
        self,
        project_id: uuid.UUID,
        *,
        since: datetime,
        until: datetime | None = None,
    ) -> ProductionMonitoring:
        since = _utc(since)
        until = _utc(until or datetime.now(tz=UTC))
        if await self._projects.get_by_id(project_id) is None:
            raise ProjectNotFoundError(project_id)
        bucket = bucket_size_for_range(since, until)
        starts = _bucket_starts(since, until, bucket)

        traces = await self._traces.list_with_spans_in_range(
            project_id, since=since, until=until, limit=TRACE_LIMIT + 1
        )
        truncated = len(traces) > TRACE_LIMIT
        traces = traces[:TRACE_LIMIT]

        usages = [(trace, _usage(trace)) for trace in traces]
        traffic = self._traffic(usages, since=since, bucket=bucket, starts=starts)
        live_rows = (await self._live.list_in_range(project_id, since=since, until=until)).items
        metrics = self._judge_metrics(live_rows, since, bucket, starts)
        metrics += await self._trace_score_metrics(project_id, traces, since, bucket, starts)
        n_needs_review = await self._count_needs_review(live_rows)

        def total(key: str) -> float:
            return sum(u.get(key, 0.0) for _, u in usages)

        return ProductionMonitoring(
            since=since,
            until=until,
            bucket_seconds=int(bucket.total_seconds()),
            n_traces=len(traces),
            n_errors=sum(1 for t in traces if t.status == "error"),
            latency=latency_percentiles([u["latency_ms"] for _, u in usages if "latency_ms" in u]),
            prompt_tokens=total("prompt_tokens"),
            completion_tokens=total("completion_tokens"),
            total_tokens=total("total_tokens"),
            cost_usd=total("cost_usd"),
            traces_truncated=truncated,
            n_needs_review=n_needs_review,
            traffic=traffic,
            metrics=metrics,
        )

    @staticmethod
    def _traffic(
        usages: list[tuple[Trace, dict[str, float]]],
        *,
        since: datetime,
        bucket: timedelta,
        starts: list[datetime],
    ) -> list[TrafficBucket]:
        per_bucket: dict[int, list[tuple[Trace, dict[str, float]]]] = defaultdict(list)
        for trace, usage in usages:
            idx = _bucket_of(trace.start_time, since, bucket, len(starts))
            if idx is not None:
                per_bucket[idx].append((trace, usage))
        series: list[TrafficBucket] = []
        for idx, start in enumerate(starts):
            rows = per_bucket.get(idx, [])
            series.append(
                TrafficBucket(
                    bucket_start=start,
                    n_traces=len(rows),
                    n_errors=sum(1 for t, _ in rows if t.status == "error"),
                    latency=latency_percentiles(
                        [u["latency_ms"] for _, u in rows if "latency_ms" in u]
                    ),
                    total_tokens=sum(u.get("total_tokens", 0.0) for _, u in rows),
                    cost_usd=sum(u.get("cost_usd", 0.0) for _, u in rows),
                )
            )
        return series

    @staticmethod
    def _judge_metrics(
        live_rows: list[LiveInteractionInRange],
        since: datetime,
        bucket: timedelta,
        starts: list[datetime],
    ) -> list[MetricMonitor]:
        samples: dict[str, list[_Sample]] = defaultdict(list)
        for row in sorted(live_rows, key=lambda r: r.interaction.created_at):
            for score in row.scores:
                samples[score.kind].append(
                    _Sample(
                        at=row.interaction.created_at,
                        value=score.score,
                        failed=score_is_failed(score),
                        threshold=score.threshold,
                    )
                )
        return [
            _metric_monitor(kind, "judge", rows, since=since, bucket=bucket, starts=starts)
            for kind, rows in sorted(samples.items())
        ]

    async def _trace_score_metrics(
        self,
        project_id: uuid.UUID,
        traces: list[Trace],
        since: datetime,
        bucket: timedelta,
        starts: list[datetime],
    ) -> list[MetricMonitor]:
        started = {t.trace_id: t.start_time for t in traces}
        ids = sorted(started)
        samples: dict[tuple[str, str], list[_Sample]] = defaultdict(list)
        for offset in range(0, len(ids), _TRACE_SCORE_CHUNK):
            chunk = ids[offset : offset + _TRACE_SCORE_CHUNK]
            by_trace = await self._trace_scores.list_by_trace_ids(project_id, chunk)
            for trace_id, scores in by_trace.items():
                for score in scores:
                    samples[(score.name, score.source)].append(
                        _Sample(
                            at=started[trace_id],
                            value=score.value,
                            failed=trace_score_is_failed(score),
                            threshold=score.threshold,
                        )
                    )
        out: list[MetricMonitor] = []
        for (name, source), rows in sorted(samples.items()):
            rows.sort(key=lambda s: _utc(s.at))
            out.append(
                _metric_monitor(name, source, rows, since=since, bucket=bucket, starts=starts)
            )
        return out

    async def _count_needs_review(self, live_rows: list[LiveInteractionInRange]) -> int:
        """Judged answers no human has reviewed yet (the annotation queue size)."""
        score_ids = [s.id for row in live_rows for s in row.scores]
        reviewed: set[uuid.UUID] = set()
        for offset in range(0, len(score_ids), _REVIEW_CHUNK):
            chunk = score_ids[offset : offset + _REVIEW_CHUNK]
            reviewed.update(await self._live.list_score_reviews_by_score_ids(chunk))
        return sum(
            1 for row in live_rows if row.scores and not any(s.id in reviewed for s in row.scores)
        )
