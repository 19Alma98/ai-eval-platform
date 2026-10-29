"""Alert rules evaluated by the server on production monitoring data.

Every ``ALERTS_INTERVAL_SECONDS`` the API process evaluates enabled rules over their
window (the same numbers as the Production page). A rule that starts breaching its
threshold fires once, a rule that recovers resolves once; ``repeat_minutes`` re-sends
while it keeps firing. Each notification is logged as an alert event and, when a
webhook is configured (per rule, else ``ALERT_WEBHOOK_URL``), POSTed to it.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from opengrade_server.application.monitoring import GetProductionMonitoring, ProductionMonitoring
from opengrade_server.application.projects import ProjectNotFoundError
from opengrade_server.domain.alert import (
    DEFAULT_MIN_SAMPLES,
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


def metric_label(rule: AlertRule) -> str:
    label = _METRIC_LABELS.get(rule.metric, rule.metric)
    if rule.score_name:
        source = f" ({rule.score_source})" if rule.score_source else ""
        return f"{rule.score_name}{source} {label}"
    return label


def format_value(rule: AlertRule, value: float | None) -> str:
    if value is None:
        return "no data"
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


def alert_message(rule: AlertRule, kind: str, value: float | None, project_name: str) -> str:
    op = ">" if rule.operator == "gt" else "<"
    head = {
        "firing": "FIRING",
        "repeat": "STILL FIRING",
        "resolved": "RESOLVED",
        "test": "TEST",
    }.get(kind, kind.upper())
    return (
        f"[OpenGrade] {head} {project_name} / {rule.name}: {metric_label(rule)} "
        f"{format_value(rule, value)} (alert when {op} {format_value(rule, rule.threshold)}, "
        f"last {_window(rule.window_minutes)})"
    )


def next_state(rule: AlertRule, reading: MetricReading) -> str:
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
    ) -> AlertEvent:
        message = alert_message(rule, kind, value, project_name)
        url = rule.webhook_url or self._default_webhook_url
        status, error = "skipped", None
        if url:
            payload = self._payload(rule, kind, value, samples, project_name, message)
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
            },
            "value": value,
            "samples": samples,
            "url": link,
            "at": datetime.now(UTC).isoformat(),
        }


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
        # One monitoring pass per (project, window): rules on the same window share it.
        cache: dict[tuple[uuid.UUID, int], ProductionMonitoring | None] = {}
        names: dict[uuid.UUID, str] = {}
        for rule in rules:
            key = (rule.project_id, rule.window_minutes)
            if key not in cache:
                try:
                    cache[key] = await self._monitoring.execute(
                        rule.project_id,
                        since=now - timedelta(minutes=rule.window_minutes),
                        until=now,
                    )
                except ProjectNotFoundError:
                    cache[key] = None
            monitoring = cache[key]
            if monitoring is None:
                continue
            if rule.project_id not in names:
                project = await self._projects.get_by_id(rule.project_id)
                names[rule.project_id] = project.name if project else str(rule.project_id)
            out.append(await self._evaluate(rule, monitoring, now, names[rule.project_id]))
        return out

    async def _evaluate(
        self,
        rule: AlertRule,
        monitoring: ProductionMonitoring,
        now: datetime,
        project_name: str,
    ) -> RuleEvaluation:
        reading = read_metric(rule, monitoring)
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
            )
        updated = await self._alerts.update_rule(
            replace(
                rule,
                state=state,
                last_value=reading.value,
                last_evaluated_at=now,
                last_notified_at=now if event is not None else rule.last_notified_at,
            )
        )
        return RuleEvaluation(
            rule=updated, value=reading.value, samples=reading.samples, event=event
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
    clear: frozenset[str] = frozenset()


_CLEARABLE = frozenset({"score_name", "score_source", "webhook_url", "repeat_minutes"})
_CONDITION_FIELDS = frozenset(
    {
        "metric",
        "operator",
        "threshold",
        "window_minutes",
        "min_samples",
        "score_name",
        "score_source",
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
            )
            if (value := getattr(fields, name)) is not None
        }
        changes.update({name: None for name in fields.clear})
        changed_condition = bool(_CONDITION_FIELDS & set(changes))
        if "metric" in changes and "min_samples" not in changes:
            sampled = changes["metric"] in SAMPLED_METRICS
            changes["min_samples"] = DEFAULT_MIN_SAMPLES if sampled else 0
        updated = replace(rule, **changes, updated_at=datetime.now(UTC)).validated()
        if changed_condition or ("enabled" in changes and not changes["enabled"]):
            # A new condition starts from scratch: no stale "firing" or "resolved".
            updated = replace(updated, state="no_data", last_value=None, last_notified_at=None)
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
