"""Alert rules evaluated by the server on production monitoring data.

Every ``ALERTS_INTERVAL_SECONDS`` the API process evaluates enabled rules over their
window (the same numbers as the Production page). A rule that starts breaching its
threshold fires once, a rule that recovers resolves once; ``repeat_minutes`` re-sends
while it keeps firing. Each notification is logged as an alert event and, when a
webhook is configured (per rule, else ``ALERT_WEBHOOK_URL``), POSTed to it.

Conditions:

- ``threshold``: the metric over the window vs a fixed number.
- ``change`` (drift): relative change of the metric vs the ``baseline_minutes`` right
  before the window, e.g. groundedness mean down 20% vs the previous week.
- ``anomaly``: z-score of the metric vs the same metric over the past windows of the
  same size (``baseline_minutes / window_minutes`` of them), e.g. p90 latency 3 standard
  deviations above what the last 24 hours looked like. Past windows are aligned to
  multiples of ``window_minutes`` so their monitoring numbers can be cached.
"""

from __future__ import annotations

import asyncio
import logging
import math
import statistics
import uuid
from collections import OrderedDict
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from opengrade_server.application.monitoring import GetProductionMonitoring, ProductionMonitoring
from opengrade_server.application.projects import ProjectNotFoundError
from opengrade_server.domain.alert import (
    DEFAULT_MIN_SAMPLES,
    MIN_ANOMALY_BUCKETS,
    SAMPLED_METRICS,
    AlertEvent,
    AlertRule,
    AlertRuleValidationError,
)
from opengrade_server.domain.repositories import AlertRepository, ProjectRepository

logger = logging.getLogger(__name__)

_METRIC_LABELS = {
    "error_rate": "error rate",
    "latency_p50_ms": "latency p50",
    "latency_p90_ms": "latency p90",
    "latency_p99_ms": "latency p99",
    "traffic": "traces",
    "cost_usd": "cost",
    "total_tokens": "tokens",
    "needs_review": "answers awaiting review",
    "score_mean": "mean",
    "score_fail_rate": "fail rate",
}


# Metrics that are sums over the window (not rates / percentiles / means).
TOTAL_METRICS = frozenset({"traffic", "cost_usd", "total_tokens"})


class AlertRuleNotFoundError(Exception):
    def __init__(self, rule_id: uuid.UUID) -> None:
        super().__init__(f"Alert rule not found: {rule_id}")


class AlertNotifier(Protocol):
    async def send(self, url: str, payload: dict[str, Any]) -> str | None:
        """POST ``payload``; return an error message, or None when delivered."""
        ...


@dataclass(frozen=True, slots=True)
class MetricReading:
    value: float | None
    samples: int


def read_metric(rule: AlertRule, monitoring: ProductionMonitoring) -> MetricReading:
    """The rule's metric over the monitoring window, with how many samples back it."""
    n = monitoring.n_traces
    if rule.metric == "error_rate":
        return MetricReading(monitoring.n_errors / n if n else None, n)
    if rule.metric == "latency_p50_ms":
        return MetricReading(monitoring.latency.p50_ms, n)
    if rule.metric == "latency_p90_ms":
        return MetricReading(monitoring.latency.p90_ms, n)
    if rule.metric == "latency_p99_ms":
        return MetricReading(monitoring.latency.p99_ms, n)
    if rule.metric == "traffic":
        return MetricReading(float(n), n)
    if rule.metric == "cost_usd":
        return MetricReading(monitoring.cost_usd, n)
    if rule.metric == "total_tokens":
        return MetricReading(monitoring.total_tokens, n)
    if rule.metric == "needs_review":
        return MetricReading(float(monitoring.n_needs_review), monitoring.n_needs_review)
    matches = [
        m
        for m in monitoring.metrics
        if m.name == rule.score_name and (rule.score_source in (None, m.source))
    ]
    samples = sum(m.n for m in matches)
    attr = "mean" if rule.metric == "score_mean" else "fail_rate"
    weighted = [(getattr(m, attr), m.n) for m in matches if getattr(m, attr) is not None]
    total = sum(w for _, w in weighted)
    if not total:
        return MetricReading(None, samples)
    return MetricReading(sum(v * w for v, w in weighted) / total, samples)


@dataclass(frozen=True, slots=True)
class RuleReading:
    """What a rule compares with its threshold.

    ``value`` is the metric (threshold rules), the relative change (change rules) or the
    z-score (anomaly rules); ``observed`` / ``baseline`` are the raw metric now and its
    baseline (None for threshold rules).
    """

    value: float | None
    samples: int
    observed: float | None = None
    baseline: float | None = None
    baseline_std: float | None = None
    baseline_windows: int = 0


def relative_change(observed: float | None, baseline: float | None) -> float | None:
    """(observed - baseline) / |baseline|; None when either is missing or baseline is 0."""
    if observed is None or baseline is None or baseline == 0:
        return None
    return (observed - baseline) / abs(baseline)


def z_score(observed: float, history: list[float]) -> tuple[float, float, float]:
    """(z, mean, std) of ``observed`` against ``history`` (at least 2 values).

    The std has a floor of 1% of |mean| (and 1e-9) so a perfectly flat history does not
    turn a tiny wobble into an infinite z-score.
    """
    mean = statistics.fmean(history)
    std = statistics.stdev(history)
    floor = max(abs(mean) * 0.01, 1e-9)
    return (observed - mean) / max(std, floor), mean, std


def metric_label(rule: AlertRule) -> str:
    label = _METRIC_LABELS.get(rule.metric, rule.metric)
    if rule.score_name:
        source = f" ({rule.score_source})" if rule.score_source else ""
        return f"{rule.score_name}{source} {label}"
    return label


def format_metric(rule: AlertRule, value: float | None) -> str:
    """Format a raw metric value (ignores the rule's condition)."""
    return format_value(replace(rule, condition="threshold"), value)


def format_value(rule: AlertRule, value: float | None) -> str:
    """Format what the rule compares: the metric, a relative change or a z-score."""
    if value is None:
        return "no data"
    if rule.condition == "change":
        return f"{value * 100:+.1f}%"
    if rule.condition == "anomaly":
        return f"z={value:+.1f}"
    if rule.metric in {"error_rate", "score_fail_rate"}:
        return f"{value * 100:.1f}%"
    if rule.metric.startswith("latency_"):
        return f"{value:.0f} ms"
    if rule.metric == "cost_usd":
        return f"${value:.4f}"
    if rule.metric == "score_mean":
        return f"{value:.3f}"
    return f"{value:.0f}"


def _window(minutes: int) -> str:
    if minutes % (24 * 60) == 0:
        days = minutes // (24 * 60)
        return f"{days} day{'s' if days != 1 else ''}"
    if minutes % 60 == 0:
        hours = minutes // 60
        return f"{hours} hour{'s' if hours != 1 else ''}"
    return f"{minutes} min"


def _op(rule: AlertRule) -> str:
    if rule.operator == "abs":
        return "beyond ±"
    return ">" if rule.operator == "gt" else "<"


def _threshold_text(rule: AlertRule) -> str:
    if rule.operator == "abs":
        if rule.condition == "change":
            return f"{rule.threshold * 100:.1f}%"
        return f"{rule.threshold:.1f}"
    return format_value(rule, rule.threshold)


def alert_message(
    rule: AlertRule,
    kind: str,
    value: float | None,
    project_name: str,
    reading: RuleReading | None = None,
) -> str:
    op = _op(rule)
    head = {
        "firing": "FIRING",
        "repeat": "STILL FIRING",
        "resolved": "RESOLVED",
        "test": "TEST",
    }.get(kind, kind.upper())
    scope = ", ".join(
        f"{label} {value}"
        for label, value in (("env", rule.environment), ("version", rule.version))
        if value
    )
    where = f" [{scope}]" if scope else ""
    prefix = f"[OpenGrade] {head} {project_name}{where} / {rule.name}: {metric_label(rule)}"
    if rule.condition == "threshold":
        return (
            f"{prefix} {format_value(rule, value)} (alert when {op} "
            f"{_threshold_text(rule)}, last {_window(rule.window_minutes)})"
        )
    observed = reading.observed if reading is not None else rule.last_observed
    baseline = reading.baseline if reading is not None else rule.last_baseline
    period = _window(rule.baseline_minutes or rule.window_minutes)
    if rule.condition == "change":
        compared = f"previous {period}"
        what = "change"
    else:
        compared = f"the {rule.anomaly_buckets} windows of the previous {period}"
        what = "z-score"
    return (
        f"{prefix} {format_metric(rule, observed)} vs {format_metric(rule, baseline)} "
        f"baseline ({format_value(rule, value)}; alert when {what} {op} "
        f"{_threshold_text(rule)}, last {_window(rule.window_minutes)} vs {compared})"
    )


def next_state(rule: AlertRule, reading: MetricReading | RuleReading) -> str:
    if reading.value is None or reading.samples < rule.min_samples:
        return "no_data"
    return "firing" if rule.breached(reading.value) else "ok"


def notification_kind(rule: AlertRule, state: str, now: datetime) -> str | None:
    """Which notification a transition to ``state`` sends, if any."""
    if state == "firing" and rule.state != "firing":
        return "firing"
    if state == "ok" and rule.state == "firing":
        return "resolved"
    if state == "firing" and rule.repeat_minutes and rule.last_notified_at is not None:
        if now - rule.last_notified_at >= timedelta(minutes=rule.repeat_minutes):
            return "repeat"
    return None


@dataclass(frozen=True, slots=True)
class RuleEvaluation:
    rule: AlertRule
    value: float | None
    samples: int
    event: AlertEvent | None
    reading: RuleReading | None = None


class AlertDispatcher:
    """Builds the webhook payload, delivers it and records the event."""

    def __init__(
        self,
        alerts: AlertRepository,
        notifier: AlertNotifier,
        *,
        default_webhook_url: str | None = None,
        public_base_url: str | None = None,
    ) -> None:
        self._alerts = alerts
        self._notifier = notifier
        self._default_webhook_url = default_webhook_url
        self._public_base_url = public_base_url.rstrip("/") if public_base_url else None

    async def dispatch(
        self,
        rule: AlertRule,
        *,
        kind: str,
        value: float | None,
        samples: int,
        project_name: str,
        reading: RuleReading | None = None,
    ) -> AlertEvent:
        message = alert_message(rule, kind, value, project_name, reading)
        url = rule.webhook_url or self._default_webhook_url
        status, error = "skipped", None
        if url:
            payload = self._payload(rule, kind, value, samples, project_name, message)
            if rule.condition != "threshold" and rule.webhook_format == "json":
                payload["observed"] = reading.observed if reading else rule.last_observed
                payload["baseline"] = reading.baseline if reading else rule.last_baseline
            try:
                error = await self._notifier.send(url, payload)
            except Exception as exc:  # noqa: BLE001 — delivery must never break evaluation
                error = f"{type(exc).__name__}: {exc}"
            status = "failed" if error else "sent"
            if error:
                logger.warning("Alert %s webhook delivery failed: %s", rule.id, error)
        event = AlertEvent.create(
            rule,
            kind=kind,
            value=value,
            message=message,
            delivery_status=status,
            delivery_error=error,
        )
        return await self._alerts.add_event(event)

    def _payload(
        self,
        rule: AlertRule,
        kind: str,
        value: float | None,
        samples: int,
        project_name: str,
        message: str,
    ) -> dict[str, Any]:
        link = (
            f"{self._public_base_url}/monitoring?project={rule.project_id}"
            if self._public_base_url
            else None
        )
        text = f"{message}\n{link}" if link else message
        if rule.webhook_format == "slack":
            return {"text": text}
        return {
            "text": text,
            "event": kind,
            "project": {"id": str(rule.project_id), "name": project_name},
            "rule": {
                "id": str(rule.id),
                "name": rule.name,
                "metric": rule.metric,
                "score_name": rule.score_name,
                "score_source": rule.score_source,
                "operator": rule.operator,
                "threshold": rule.threshold,
                "window_minutes": rule.window_minutes,
                "environment": rule.environment,
                "version": rule.version,
                "condition": rule.condition,
                "baseline_minutes": rule.baseline_minutes,
            },
            "value": value,
            "samples": samples,
            "url": link,
            "at": datetime.now(UTC).isoformat(),
        }


# Monitoring numbers of past, aligned baseline windows: (project, env, version, start,
# minutes) -> ProductionMonitoring. Shared across evaluation passes (one per minute).
_BASELINE_CACHE: OrderedDict[
    tuple[uuid.UUID, str | None, str | None, datetime, int], ProductionMonitoring
] = OrderedDict()
_BASELINE_CACHE_MAX = 4096
# A window this recent may still receive late spans / judge scores: not cached.
_BASELINE_SETTLE = timedelta(minutes=15)


def clear_baseline_cache() -> None:
    _BASELINE_CACHE.clear()


def anomaly_windows(rule: AlertRule, now: datetime) -> list[tuple[datetime, datetime]]:
    """Past windows (oldest first) an anomaly rule compares the current window with.

    They end at the last multiple of ``window_minutes`` (since the epoch) before the
    current window starts, so the same windows recur from one minute to the next.
    """
    width = timedelta(minutes=rule.window_minutes)
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    current_start = now - width
    aligned_end = epoch + ((current_start - epoch) // width) * width
    n = rule.anomaly_buckets
    return [(aligned_end - (n - i) * width, aligned_end - (n - i - 1) * width) for i in range(n)]


class EvaluateAlertRules:
    def __init__(
        self,
        alerts: AlertRepository,
        projects: ProjectRepository,
        monitoring: GetProductionMonitoring,
        dispatcher: AlertDispatcher,
    ) -> None:
        self._alerts = alerts
        self._projects = projects
        self._monitoring = monitoring
        self._dispatcher = dispatcher

    async def execute(
        self,
        *,
        project_id: uuid.UUID | None = None,
        now: datetime | None = None,
    ) -> list[RuleEvaluation]:
        now = now or datetime.now(UTC)
        if project_id is not None:
            rules = [r for r in await self._alerts.list_rules(project_id) if r.enabled]
        else:
            rules = await self._alerts.list_enabled_rules()
        out: list[RuleEvaluation] = []
        # One monitoring pass per (project, period): rules on the same period share it.
        cache: dict[
            tuple[uuid.UUID, datetime, datetime, str | None, str | None],
            ProductionMonitoring | None,
        ] = {}
        names: dict[uuid.UUID, str] = {}
        for rule in rules:
            try:
                reading = await self._reading(rule, now, cache)
            except ProjectNotFoundError:
                continue
            if reading is None:
                continue
            if rule.project_id not in names:
                project = await self._projects.get_by_id(rule.project_id)
                names[rule.project_id] = project.name if project else str(rule.project_id)
            out.append(await self._evaluate(rule, reading, now, names[rule.project_id]))
        return out

    async def _monitoring_for(
        self,
        rule: AlertRule,
        since: datetime,
        until: datetime,
        cache: dict[
            tuple[uuid.UUID, datetime, datetime, str | None, str | None],
            ProductionMonitoring | None,
        ],
    ) -> ProductionMonitoring | None:
        key = (rule.project_id, since, until, rule.environment, rule.version)
        if key not in cache:
            try:
                cache[key] = await self._monitoring.execute(
                    rule.project_id,
                    since=since,
                    until=until,
                    environment=rule.environment,
                    version=rule.version,
                )
            except ProjectNotFoundError:
                cache[key] = None
        return cache[key]

    async def _past_window(
        self,
        rule: AlertRule,
        since: datetime,
        until: datetime,
        now: datetime,
        cache: dict[
            tuple[uuid.UUID, datetime, datetime, str | None, str | None],
            ProductionMonitoring | None,
        ],
    ) -> ProductionMonitoring | None:
        minutes = int((until - since).total_seconds() // 60)
        key = (rule.project_id, rule.environment, rule.version, since, minutes)
        hit = _BASELINE_CACHE.get(key)
        if hit is not None:
            _BASELINE_CACHE.move_to_end(key)
            return hit
        monitoring = await self._monitoring_for(rule, since, until, cache)
        if monitoring is not None and until <= now - _BASELINE_SETTLE:
            _BASELINE_CACHE[key] = monitoring
            while len(_BASELINE_CACHE) > _BASELINE_CACHE_MAX:
                _BASELINE_CACHE.popitem(last=False)
        return monitoring

    async def _reading(
        self,
        rule: AlertRule,
        now: datetime,
        cache: dict[
            tuple[uuid.UUID, datetime, datetime, str | None, str | None],
            ProductionMonitoring | None,
        ],
    ) -> RuleReading | None:
        """None when the project is gone."""
        window_start = now - timedelta(minutes=rule.window_minutes)
        current = await self._monitoring_for(rule, window_start, now, cache)
        if current is None:
            return None
        reading = read_metric(rule, current)
        if rule.condition == "threshold":
            return RuleReading(reading.value, reading.samples)
        if rule.condition == "change":
            baseline_start = window_start - timedelta(minutes=rule.baseline_minutes or 0)
            past = await self._monitoring_for(rule, baseline_start, window_start, cache)
            if past is None:
                return None
            base = read_metric(rule, past)
            if base.samples < rule.min_samples:
                # Too little history to compare with: no data, not "no change".
                return RuleReading(None, reading.samples, reading.value, base.value)
            base_value = base.value
            if base_value is not None and rule.metric in TOTAL_METRICS:
                # Totals grow with the period: scale the baseline to one window.
                base_value *= rule.window_minutes / (rule.baseline_minutes or rule.window_minutes)
            change = relative_change(reading.value, base_value)
            return RuleReading(
                change, reading.samples, reading.value, base_value, baseline_windows=1
            )
        history: list[float] = []
        for since, until in anomaly_windows(rule, now):
            past = await self._past_window(rule, since, until, now, cache)
            if past is None:
                return None
            point = read_metric(rule, past)
            if point.value is not None and point.samples >= rule.min_samples:
                history.append(point.value)
        if reading.value is None or len(history) < MIN_ANOMALY_BUCKETS:
            mean = statistics.fmean(history) if history else None
            return RuleReading(
                None, reading.samples, reading.value, mean, baseline_windows=len(history)
            )
        z, mean, std = z_score(reading.value, history)
        return RuleReading(
            z if math.isfinite(z) else None,
            reading.samples,
            reading.value,
            mean,
            baseline_std=std,
            baseline_windows=len(history),
        )

    async def _evaluate(
        self,
        rule: AlertRule,
        reading: RuleReading,
        now: datetime,
        project_name: str,
    ) -> RuleEvaluation:
        state = next_state(rule, reading)
        kind = notification_kind(rule, state, now)
        event = None
        if kind is not None:
            event = await self._dispatcher.dispatch(
                rule,
                kind=kind,
                value=reading.value,
                samples=reading.samples,
                project_name=project_name,
                reading=reading,
            )
        updated = await self._alerts.update_rule(
            replace(
                rule,
                state=state,
                last_value=reading.value,
                last_observed=reading.observed,
                last_baseline=reading.baseline,
                last_evaluated_at=now,
                last_notified_at=now if event is not None else rule.last_notified_at,
            )
        )
        return RuleEvaluation(
            rule=updated,
            value=reading.value,
            samples=reading.samples,
            event=event,
            reading=reading,
        )


@dataclass(frozen=True, slots=True)
class AlertRuleFields:
    """Editable fields; on update, ``None`` leaves a field unchanged unless listed in
    ``clear`` (only the optional ones can be cleared)."""

    name: str | None = None
    metric: str | None = None
    operator: str | None = None
    threshold: float | None = None
    window_minutes: int | None = None
    min_samples: int | None = None
    score_name: str | None = None
    score_source: str | None = None
    webhook_url: str | None = None
    webhook_format: str | None = None
    repeat_minutes: int | None = None
    enabled: bool | None = None
    environment: str | None = None
    version: str | None = None
    condition: str | None = None
    baseline_minutes: int | None = None
    clear: frozenset[str] = frozenset()


_CLEARABLE = frozenset(
    {
        "score_name",
        "score_source",
        "webhook_url",
        "repeat_minutes",
        "environment",
        "version",
        "baseline_minutes",
    }
)
_CONDITION_FIELDS = frozenset(
    {
        "metric",
        "operator",
        "threshold",
        "window_minutes",
        "min_samples",
        "score_name",
        "score_source",
        "environment",
        "version",
        "condition",
        "baseline_minutes",
    }
)


class ManageAlertRules:
    def __init__(
        self,
        alerts: AlertRepository,
        projects: ProjectRepository,
        dispatcher: AlertDispatcher,
    ) -> None:
        self._alerts = alerts
        self._projects = projects
        self._dispatcher = dispatcher

    async def create(self, project_id: uuid.UUID, fields: AlertRuleFields) -> AlertRule:
        if await self._projects.get_by_id(project_id) is None:
            raise ProjectNotFoundError(project_id)
        if fields.name is None or fields.metric is None or fields.threshold is None:
            raise AlertRuleValidationError("name, metric and threshold are required")
        rule = AlertRule.create(
            project_id,
            name=fields.name,
            metric=fields.metric,
            operator=fields.operator or "gt",
            threshold=fields.threshold,
            window_minutes=fields.window_minutes or 60,
            min_samples=fields.min_samples,
            score_name=fields.score_name,
            score_source=fields.score_source,
            webhook_url=fields.webhook_url,
            webhook_format=fields.webhook_format or "json",
            repeat_minutes=fields.repeat_minutes,
            enabled=True if fields.enabled is None else fields.enabled,
            environment=fields.environment,
            version=fields.version,
            condition=fields.condition or "threshold",
            baseline_minutes=fields.baseline_minutes,
        )
        return await self._alerts.add_rule(rule)

    async def list_rules(self, project_id: uuid.UUID) -> list[AlertRule]:
        if await self._projects.get_by_id(project_id) is None:
            raise ProjectNotFoundError(project_id)
        return await self._alerts.list_rules(project_id)

    async def get(self, rule_id: uuid.UUID) -> AlertRule:
        rule = await self._alerts.get_rule(rule_id)
        if rule is None:
            raise AlertRuleNotFoundError(rule_id)
        return rule

    async def update(self, rule_id: uuid.UUID, fields: AlertRuleFields) -> AlertRule:
        rule = await self.get(rule_id)
        unknown = fields.clear - _CLEARABLE
        if unknown:
            raise AlertRuleValidationError(f"cannot clear {sorted(unknown)}")
        changes: dict[str, Any] = {
            name: value
            for name in (
                "name",
                "metric",
                "operator",
                "threshold",
                "window_minutes",
                "min_samples",
                "score_name",
                "score_source",
                "webhook_url",
                "webhook_format",
                "repeat_minutes",
                "enabled",
                "environment",
                "version",
                "condition",
                "baseline_minutes",
            )
            if (value := getattr(fields, name)) is not None
        }
        changes.update({name: None for name in fields.clear})
        changed_condition = bool(_CONDITION_FIELDS & set(changes))
        if "metric" in changes and "min_samples" not in changes:
            sampled = changes["metric"] in SAMPLED_METRICS
            changes["min_samples"] = DEFAULT_MIN_SAMPLES if sampled else 0
        if ("condition" in changes or "window_minutes" in changes) and (
            "baseline_minutes" not in changes
        ):
            # Re-derive the default comparison period for the new condition / window.
            changes["baseline_minutes"] = None
        updated = replace(rule, **changes, updated_at=datetime.now(UTC)).validated()
        if changed_condition or ("enabled" in changes and not changes["enabled"]):
            # A new condition starts from scratch: no stale "firing" or "resolved".
            updated = replace(
                updated,
                state="no_data",
                last_value=None,
                last_observed=None,
                last_baseline=None,
                last_notified_at=None,
            )
        return await self._alerts.update_rule(updated)

    async def delete(self, rule_id: uuid.UUID) -> None:
        if not await self._alerts.delete_rule(rule_id):
            raise AlertRuleNotFoundError(rule_id)

    async def events(
        self, project_id: uuid.UUID, *, rule_id: uuid.UUID | None = None, limit: int = 50
    ) -> list[AlertEvent]:
        if await self._projects.get_by_id(project_id) is None:
            raise ProjectNotFoundError(project_id)
        return await self._alerts.list_events(project_id, rule_id=rule_id, limit=limit)

    async def send_test(self, rule_id: uuid.UUID) -> AlertEvent:
        rule = await self.get(rule_id)
        project = await self._projects.get_by_id(rule.project_id)
        return await self._dispatcher.dispatch(
            rule,
            kind="test",
            value=rule.last_value,
            samples=0,
            project_name=project.name if project else str(rule.project_id),
        )


async def run_alert_loop(interval_seconds: float) -> None:
    """Evaluate every enabled rule each ``interval_seconds`` (lifespan task)."""
    from opengrade_server.config import get_settings
    from opengrade_server.infrastructure.db import try_get_session_factory
    from opengrade_server.infrastructure.repositories import (
        SqlAlchemyAlertRepository,
        SqlAlchemyLiveInteractionRepository,
        SqlAlchemyProjectRepository,
        SqlAlchemyTraceRepository,
        SqlAlchemyTraceScoreRepository,
    )
    from opengrade_server.infrastructure.webhooks import HttpWebhookNotifier

    notifier = HttpWebhookNotifier()
    while True:
        await asyncio.sleep(interval_seconds)
        factory = try_get_session_factory()
        if factory is None:
            continue
        settings = get_settings()
        try:
            async with factory() as session:
                alerts = SqlAlchemyAlertRepository(session)
                projects = SqlAlchemyProjectRepository(session)
                use_case = EvaluateAlertRules(
                    alerts,
                    projects,
                    GetProductionMonitoring(
                        projects,
                        SqlAlchemyTraceRepository(session),
                        SqlAlchemyLiveInteractionRepository(session),
                        SqlAlchemyTraceScoreRepository(session),
                    ),
                    AlertDispatcher(
                        alerts,
                        notifier,
                        default_webhook_url=settings.alert_webhook_url,
                        public_base_url=settings.public_base_url,
                    ),
                )
                await use_case.execute()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Alert evaluation failed")
