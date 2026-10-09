from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from aiobs.application.compare import CompareExperiments
from aiobs.application.live_interactions import score_is_failed
from aiobs.application.live_judge_calibration import SummarizeLiveJudgeCalibration
from aiobs.application.projects import ProjectNotFoundError
from aiobs.domain.live_overview import (
    LiveAttentionItem,
    LiveInteractionInRange,
    LiveOverviewStats,
    LiveSeriesBucket,
)
from aiobs.domain.repositories import (
    DatasetRepository,
    ExperimentRepository,
    LiveInteractionRepository,
    MetricsSetRepository,
    ProjectRepository,
)

__all__ = [
    "CalibrationAlert",
    "GetProjectOverview",
    "LiveAttentionItem",
    "LiveInteractionInRange",
    "LiveOverviewStats",
    "LiveSeriesBucket",
    "OfflineOverview",
    "OverviewCompare",
    "OverviewCompareMetric",
    "OverviewExperimentRef",
    "OverviewMetricsSetRef",
    "OverviewRegression",
    "ProjectOverviewResult",
    "bucket_size_for_range",
]

_ATTENTION_LIMIT = 8
_QUESTION_PREVIEW_LEN = 200

_STATUS_MAP = {
    "regression": "regressed",
    "improved": "improved",
    "unchanged": "unchanged",
    "config_mismatch": "config_mismatch",
    "insufficient_n": "insufficient_n",
    "unavailable": "unavailable",
}


def bucket_size_for_range(since: datetime, until: datetime) -> timedelta:
    span = until - since
    if span <= timedelta(hours=1):
        return timedelta(minutes=5)
    if span <= timedelta(hours=6):
        return timedelta(minutes=15)
    if span <= timedelta(days=1):
        return timedelta(hours=1)
    return timedelta(hours=6)


@dataclass(frozen=True, slots=True)
class OverviewMetricsSetRef:
    id: uuid.UUID
    name: str
    version: int
    is_default: bool


@dataclass(frozen=True, slots=True)
class OverviewExperimentRef:
    id: uuid.UUID
    name: str
    status: str
    created_at: datetime
    baseline_experiment_id: uuid.UUID | None


@dataclass(frozen=True, slots=True)
class OverviewCompareMetric:
    name: str
    metric: str
    candidate: float | None
    baseline: float | None
    delta: float | None
    status: str


@dataclass(frozen=True, slots=True)
class OverviewCompare:
    candidate_experiment_id: uuid.UUID
    baseline_experiment_id: uuid.UUID
    metrics: list[OverviewCompareMetric]


@dataclass(frozen=True, slots=True)
class OverviewRegression:
    name: str
    delta: float | None
    status: str


@dataclass(frozen=True, slots=True)
class CalibrationAlert:
    kind: str
    agreement_rate: float
    n_reviewed: int


@dataclass(frozen=True, slots=True)
class OfflineOverview:
    n_datasets: int
    metrics_set: OverviewMetricsSetRef | None
    reference_threshold: float | None
    latest_experiment: OverviewExperimentRef | None
    release_ready: bool
    compare: OverviewCompare | None
    regressions: list[OverviewRegression]


@dataclass(frozen=True, slots=True)
class ProjectOverviewResult:
    generated_at: datetime
    since: datetime
    until: datetime
    live: LiveOverviewStats
    offline: OfflineOverview
    calibration_alerts: list[CalibrationAlert]
    warnings: list[str] = field(default_factory=list)


def _reference_threshold(metrics_set) -> float | None:
    thresholds = [
        e.threshold for e in metrics_set.entries if e.enabled and e.threshold is not None
    ]
    return min(thresholds) if thresholds else None


def _bucket_index(ts: datetime, since: datetime, bucket: timedelta) -> int:
    if ts < since:
        return -1
    return int((ts - since) // bucket)


def _truncate_question(question: str) -> str:
    q = question.strip()
    if len(q) <= _QUESTION_PREVIEW_LEN:
        return q
    return q[: _QUESTION_PREVIEW_LEN - 1] + "…"


def _aggregate_live(
    rows: list[LiveInteractionInRange],
    *,
    since: datetime,
    until: datetime,
    bucket: timedelta,
) -> LiveOverviewStats:
    n_interactions = len(rows)
    if n_interactions == 0:
        return LiveOverviewStats(
            n_interactions=0,
            n_failed=0,
            n_pending=0,
            mean_score=None,
            fail_rate=None,
            series=[],
            attention=[],
        )

    n_pending = 0
    n_failed = 0
    score_values: list[float] = []
    bucket_counts: dict[int, list[LiveInteractionInRange]] = defaultdict(list)
    failed_rows: list[LiveInteractionInRange] = []

    for row in rows:
        interaction = row.interaction
        if interaction.judge_status in ("pending", "running"):
            n_pending += 1
        failed = any(score_is_failed(s) for s in row.scores)
        if failed:
            n_failed += 1
            failed_rows.append(row)
        for s in row.scores:
            if s.score is not None:
                score_values.append(s.score)
        idx = _bucket_index(interaction.created_at, since, bucket)
        if idx >= 0:
            bucket_counts[idx].append(row)

    mean_score = sum(score_values) / len(score_values) if score_values else None
    fail_rate = n_failed / n_interactions

    series: list[LiveSeriesBucket] = []
    idx = 0
    while since + bucket * idx < until:
        bucket_rows = bucket_counts.get(idx, [])
        bucket_scores = [
            s.score for row in bucket_rows for s in row.scores if s.score is not None
        ]
        bucket_failed = sum(
            1 for row in bucket_rows if any(score_is_failed(s) for s in row.scores)
        )
        n = len(bucket_rows)
        series.append(
            LiveSeriesBucket(
                bucket_start=since + bucket * idx,
                n=n,
                mean_score=(sum(bucket_scores) / len(bucket_scores) if bucket_scores else None),
                fail_rate=(bucket_failed / n if n else None),
            )
        )
        idx += 1

    failed_rows.sort(key=lambda r: (r.interaction.created_at, r.interaction.id), reverse=True)
    attention = [
        LiveAttentionItem(
            interaction_id=row.interaction.id,
            question=_truncate_question(row.interaction.question),
            created_at=row.interaction.created_at,
            reason="fail",
        )
        for row in failed_rows[:_ATTENTION_LIMIT]
    ]

    return LiveOverviewStats(
        n_interactions=n_interactions,
        n_failed=n_failed,
        n_pending=n_pending,
        mean_score=mean_score,
        fail_rate=fail_rate,
        series=series,
        attention=attention,
    )


class GetProjectOverview:
    def __init__(
        self,
        projects: ProjectRepository,
        datasets: DatasetRepository,
        metrics_sets: MetricsSetRepository,
        experiments: ExperimentRepository,
        live: LiveInteractionRepository,
        compare: CompareExperiments,
        calibration: SummarizeLiveJudgeCalibration,
    ) -> None:
        self._projects = projects
        self._datasets = datasets
        self._metrics_sets = metrics_sets
        self._experiments = experiments
        self._live = live
        self._compare = compare
        self._calibration = calibration

    async def execute(
        self,
        project_id: uuid.UUID,
        *,
        since: datetime,
        until: datetime | None = None,
    ) -> ProjectOverviewResult:
        until = until or datetime.now(tz=UTC)
        if until.tzinfo is None:
            until = until.replace(tzinfo=UTC)
        if since.tzinfo is None:
            since = since.replace(tzinfo=UTC)

        project = await self._projects.get_by_id(project_id)
        if project is None:
            raise ProjectNotFoundError(project_id)

        warnings: list[str] = []
        bucket = bucket_size_for_range(since, until)
        live_range = await self._live.list_in_range(
            project_id, since=since, until=until
        )
        if live_range.truncated:
            warnings.append("live_truncated")
        live = _aggregate_live(
            live_range.items, since=since, until=until, bucket=bucket
        )

        datasets = await self._datasets.list_by_project(project_id)
        metrics_set = await self._metrics_sets.get_project_default(project_id)
        metrics_ref = None
        ref_threshold = None
        if metrics_set is not None:
            metrics_ref = OverviewMetricsSetRef(
                id=metrics_set.id,
                name=metrics_set.name,
                version=metrics_set.version,
                is_default=True,
            )
            ref_threshold = _reference_threshold(metrics_set)

        experiments = await self._experiments.list_by_project(project_id)
        latest = experiments[0] if experiments else None
        latest_ref = None
        release_ready = any(e.status == "completed" for e in experiments)
        compare_dto = None
        regressions: list[OverviewRegression] = []

        if latest is not None:
            latest_ref = OverviewExperimentRef(
                id=latest.id,
                name=latest.name,
                status=latest.status,
                created_at=latest.created_at,
                baseline_experiment_id=latest.baseline_experiment_id,
            )
            if latest.baseline_experiment_id is not None:
                try:
                    comparison = await self._compare.execute(
                        latest.id, latest.baseline_experiment_id
                    )
                    pass_metrics = [
                        m for m in comparison.metrics if m.metric == "pass_rate"
                    ][:10]
                    compare_dto = OverviewCompare(
                        candidate_experiment_id=comparison.experiment_id,
                        baseline_experiment_id=comparison.baseline_experiment_id,
                        metrics=[
                            OverviewCompareMetric(
                                name=m.evaluator_name or str(m.evaluator_id),
                                metric=m.metric,
                                candidate=m.candidate,
                                baseline=m.baseline,
                                delta=m.delta,
                                status=_STATUS_MAP.get(m.status, m.status),
                            )
                            for m in pass_metrics
                        ],
                    )
                    regressions = [
                        OverviewRegression(
                            name=m.evaluator_name or str(m.evaluator_id),
                            delta=m.delta,
                            status="regressed",
                        )
                        for m in comparison.regressions
                        if m.metric == "pass_rate"
                    ]
                except Exception:
                    warnings.append("compare_unavailable")
                    compare_dto = None
                    regressions = []

        calibration_alerts: list[CalibrationAlert] = []
        try:
            buckets = await self._calibration.execute(project_id, since=since)
            calibration_alerts = [
                CalibrationAlert(
                    kind=b.kind,
                    agreement_rate=b.agreement_rate,
                    n_reviewed=b.n_reviewed,
                )
                for b in buckets
                if b.n_reviewed >= 5 and b.agreement_rate < 0.7
            ]
        except Exception:
            warnings.append("calibration_unavailable")

        return ProjectOverviewResult(
            generated_at=datetime.now(tz=UTC),
            since=since,
            until=until,
            live=live,
            offline=OfflineOverview(
                n_datasets=len(datasets),
                metrics_set=metrics_ref,
                reference_threshold=ref_threshold,
                latest_experiment=latest_ref,
                release_ready=release_ready,
                compare=compare_dto,
                regressions=regressions,
            ),
            calibration_alerts=calibration_alerts,
            warnings=warnings,
        )
