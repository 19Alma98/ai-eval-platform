"""Drift (``change``) and ``anomaly`` alert conditions."""

from __future__ import annotations

import math
import uuid
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx2 import AsyncClient

import test_sqlite_smoke
from opengrade_server.application.alerts import (
    AlertDispatcher,
    AlertRuleFields,
    EvaluateAlertRules,
    ManageAlertRules,
    RuleReading,
    alert_message,
    anomaly_windows,
    clear_baseline_cache,
    relative_change,
    z_score,
)
from opengrade_server.application.monitoring import (
    LatencyPercentiles,
    MetricMonitor,
    ProductionMonitoring,
)
from opengrade_server.domain.alert import AlertEvent, AlertRule, AlertRuleValidationError
from opengrade_server.domain.project import Project
from test_alerts import _monitoring

sqlite_client = test_sqlite_smoke.sqlite_client

PROJECT = uuid.uuid4()
NOW = datetime(2026, 11, 2, 12, 7, tzinfo=UTC)


# --- pure helpers ---------------------------------------------------------------------


def test_relative_change_and_z_score() -> None:
    assert relative_change(0.6, 0.8) == pytest.approx(-0.25)
    assert relative_change(1.2, -1.0) == pytest.approx(2.2)
    assert relative_change(None, 1.0) is None
    assert relative_change(1.0, 0.0) is None
    z, mean, std = z_score(16.0, [10.0, 12.0, 8.0, 10.0])
    assert mean == 10.0
    assert std == pytest.approx(math.sqrt(8 / 3))
    assert z == pytest.approx(6 / math.sqrt(8 / 3))
    # Flat history: std floor at 1% of the mean, no infinite z.
    z, _, std = z_score(101.0, [100.0, 100.0, 100.0])
    assert std == 0.0
    assert z == pytest.approx(1.0)


def test_anomaly_windows_are_aligned_and_contiguous() -> None:
    rule = AlertRule.create(
        PROJECT,
        name="lat",
        metric="latency_p90_ms",
        operator="gt",
        threshold=3,
        condition="anomaly",
        window_minutes=60,
    )
    assert rule.baseline_minutes == 24 * 60
    windows = anomaly_windows(rule, NOW)
    assert len(windows) == 24
    # Current window starts 11:07; past windows end at the hour before it (11:00).
    assert windows[-1][1] == datetime(2026, 11, 2, 11, 0, tzinfo=UTC)
    assert windows[0][0] == datetime(2026, 11, 1, 11, 0, tzinfo=UTC)
    assert all(a[1] == b[0] for a, b in zip(windows, windows[1:], strict=False))
    # One minute later: the same windows (cacheable).
    assert anomaly_windows(rule, NOW + timedelta(minutes=1)) == windows


# --- validation ---------------------------------------------------------------------------


def test_condition_validation_and_defaults() -> None:
    change = AlertRule.create(
        PROJECT,
        name="g",
        metric="score_mean",
        score_name="groundedness",
        operator="lt",
        threshold=-0.2,
        condition="change",
        window_minutes=60,
    )
    assert change.baseline_minutes == 60  # previous period of the same length
    week = replace(change, baseline_minutes=7 * 24 * 60).validated()
    assert week.baseline_minutes == 7 * 24 * 60

    def bad(match: str, **kwargs: Any) -> None:
        fields: dict[str, Any] = {
            "name": "x",
            "metric": "latency_p90_ms",
            "operator": "gt",
            "threshold": 3.0,
        }
        fields.update(kwargs)
        with pytest.raises(AlertRuleValidationError, match=match):
            AlertRule.create(PROJECT, **fields)

    bad("condition must be one of", condition="trend")
    bad("only applies to change / anomaly", operator="abs")
    bad("baseline_minutes only applies", baseline_minutes=120)
    bad("threshold >= 0", condition="anomaly", operator="abs", threshold=-1.0)
    bad("between window_minutes", condition="change", baseline_minutes=30)
    bad("3-48 past windows", condition="anomaly", window_minutes=60, baseline_minutes=120)
    bad("3-48 past windows", condition="anomaly", window_minutes=5, baseline_minutes=24 * 60)
    bad("backlog count", condition="change", metric="needs_review")


def test_messages_show_observed_baseline_and_statistic() -> None:
    change = AlertRule.create(
        PROJECT,
        name="Grounding drift",
        metric="score_mean",
        score_name="groundedness",
        operator="lt",
        threshold=-0.2,
        condition="change",
        window_minutes=60,
        baseline_minutes=7 * 24 * 60,
    )
    reading = RuleReading(-0.25, 40, observed=0.6, baseline=0.8)
    assert alert_message(change, "firing", -0.25, "shop", reading) == (
        "[OpenGrade] FIRING shop / Grounding drift: groundedness mean 0.600 vs 0.800 baseline "
        "(-25.0%; alert when change < -20.0%, last 1 hour vs previous 7 days)"
    )
    anomaly = AlertRule.create(
        PROJECT,
        name="Latency spike",
        metric="latency_p90_ms",
        operator="abs",
        threshold=3,
        condition="anomaly",
        window_minutes=60,
    )
    reading = RuleReading(4.2, 50, observed=2400.0, baseline=800.0)
    assert alert_message(anomaly, "firing", 4.2, "shop", reading) == (
        "[OpenGrade] FIRING shop / Latency spike: latency p90 2400 ms vs 800 ms baseline "
        "(z=+4.2; alert when z-score beyond ± 3.0, last 1 hour vs the 24 windows of the "
        "previous 1 day)"
    )


# --- evaluation with fakes ---------------------------------------------------------------


class _Alerts:
    def __init__(self, rules: list[AlertRule]) -> None:
        self.rules = {r.id: r for r in rules}
        self.events: list[AlertEvent] = []

    async def update_rule(self, rule: AlertRule) -> AlertRule:
        self.rules[rule.id] = rule
        return rule

    async def list_rules(self, project_id: uuid.UUID) -> list[AlertRule]:
        return [r for r in self.rules.values() if r.project_id == project_id]

    async def list_enabled_rules(self) -> list[AlertRule]:
        return [r for r in self.rules.values() if r.enabled]

    async def add_event(self, event: AlertEvent) -> AlertEvent:
        self.events.append(event)
        return event


class _Projects:
    async def get_by_id(self, project_id: uuid.UUID) -> Project | None:
        return Project(id=project_id, name="shop", slug="shop", created_at=NOW)


class _Monitoring:
    """Monitoring numbers produced by ``fn(since, until)``; counts the calls."""

    def __init__(self, fn: Callable[[datetime, datetime], ProductionMonitoring]) -> None:
        self.fn = fn
        self.calls: list[tuple[datetime, datetime]] = []

    async def execute(
        self,
        project_id: uuid.UUID,
        *,
        since: datetime,
        until: datetime,
        environment: str | None = None,
        version: str | None = None,
    ) -> ProductionMonitoring:
        self.calls.append((since, until))
        return self.fn(since, until)


class _Notifier:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send(self, url: str, payload: dict[str, Any]) -> str | None:
        self.sent.append(payload)
        return None


def _use_case(
    rules: list[AlertRule], monitoring: _Monitoring
) -> tuple[EvaluateAlertRules, _Alerts, _Notifier]:
    alerts = _Alerts(rules)
    notifier = _Notifier()
    dispatcher = AlertDispatcher(alerts, notifier, default_webhook_url="http://hook")  # type: ignore[arg-type]
    return (
        EvaluateAlertRules(alerts, _Projects(), monitoring, dispatcher),  # type: ignore[arg-type]
        alerts,
        notifier,
    )


def _score(mean: float, n: int = 40) -> MetricMonitor:
    return MetricMonitor(
        name="groundedness",
        source="judge",
        n=n,
        mean=mean,
        fail_rate=None,
        threshold=None,
        histogram_edges=[],
        histogram_counts=[],
        series=[],
    )


@pytest.mark.asyncio
async def test_change_rule_fires_on_drift_and_needs_baseline_samples() -> None:
    clear_baseline_cache()
    rule = AlertRule.create(
        PROJECT,
        name="Grounding drift",
        metric="score_mean",
        score_name="groundedness",
        operator="lt",
        threshold=-0.2,
        condition="change",
        window_minutes=60,
        baseline_minutes=7 * 24 * 60,
    )

    def numbers(since: datetime, until: datetime) -> ProductionMonitoring:
        current = until == NOW
        return _monitoring(metrics=[_score(0.6 if current else 0.8)])

    use_case, alerts, notifier = _use_case([rule], _Monitoring(numbers))
    [result] = await use_case.execute(now=NOW)
    assert result.value == pytest.approx(-0.25)
    assert result.rule.state == "firing"
    assert result.rule.last_observed == pytest.approx(0.6)
    assert result.rule.last_baseline == pytest.approx(0.8)
    assert notifier.sent[0]["rule"]["condition"] == "change"
    assert notifier.sent[0]["observed"] == pytest.approx(0.6)
    assert notifier.sent[0]["baseline"] == pytest.approx(0.8)
    assert "0.600 vs 0.800 baseline" in alerts.events[0].message

    # Too few baseline samples: no data instead of a bogus comparison.
    def thin(since: datetime, until: datetime) -> ProductionMonitoring:
        return _monitoring(metrics=[_score(0.6 if until == NOW else 0.8, n=2)])

    fresh = replace(rule, state="no_data")
    use_case, _, _ = _use_case([fresh], _Monitoring(thin))
    [result] = await use_case.execute(now=NOW)
    assert result.rule.state == "no_data"
    assert result.value is None


@pytest.mark.asyncio
async def test_change_rule_scales_totals_to_one_window() -> None:
    clear_baseline_cache()
    rule = AlertRule.create(
        PROJECT,
        name="Cost up",
        metric="cost_usd",
        operator="gt",
        threshold=0.5,
        condition="change",
        window_minutes=60,
        baseline_minutes=24 * 60,
    )

    def numbers(since: datetime, until: datetime) -> ProductionMonitoring:
        # $2 in the last hour vs $24 over the previous day ($1/hour): +100%.
        return _monitoring(cost_usd=2.0 if until == NOW else 24.0)

    use_case, _, _ = _use_case([rule], _Monitoring(numbers))
    [result] = await use_case.execute(now=NOW)
    assert result.reading is not None
    assert result.reading.baseline == pytest.approx(1.0)
    assert result.value == pytest.approx(1.0)
    assert result.rule.state == "firing"


@pytest.mark.asyncio
async def test_anomaly_rule_spike_drop_and_caching() -> None:
    clear_baseline_cache()
    rule = AlertRule.create(
        PROJECT,
        name="Latency spike",
        metric="latency_p90_ms",
        operator="abs",
        threshold=3,
        condition="anomaly",
        window_minutes=60,
        baseline_minutes=6 * 60,
        min_samples=0,
    )
    current = {"p90": 2000.0}

    def numbers(since: datetime, until: datetime) -> ProductionMonitoring:
        if until >= NOW:
            p90 = current["p90"]
        else:
            p90 = 800.0 + (since.hour % 2) * 40.0  # 800 / 840 alternating
        return _monitoring(latency=LatencyPercentiles(p50_ms=100.0, p90_ms=p90, p99_ms=p90))

    monitoring = _Monitoring(numbers)
    use_case, _, _ = _use_case([rule], monitoring)
    [result] = await use_case.execute(now=NOW)
    assert result.reading is not None
    assert result.reading.baseline_windows == 6
    assert result.reading.baseline == pytest.approx(820.0)
    assert result.value is not None and result.value > 3
    assert result.rule.state == "firing"
    assert len(monitoring.calls) == 7  # current window + 6 past windows

    # A minute later the past windows come from the cache: one query (current window).
    current["p90"] = 600.0  # big drop: still anomalous with operator abs
    use_case, _, _ = _use_case([result.rule], monitoring)
    [again] = await use_case.execute(now=NOW + timedelta(minutes=1))
    assert len(monitoring.calls) == 8
    assert again.value is not None and again.value < -3
    assert again.rule.state == "firing"

    current["p90"] = 830.0
    use_case, _, _ = _use_case([again.rule], monitoring)
    [normal] = await use_case.execute(now=NOW + timedelta(minutes=2))
    assert normal.rule.state == "ok"


@pytest.mark.asyncio
async def test_anomaly_rule_needs_enough_history() -> None:
    clear_baseline_cache()
    rule = AlertRule.create(
        PROJECT,
        name="Errors",
        metric="error_rate",
        operator="gt",
        threshold=3,
        condition="anomaly",
        window_minutes=60,
        baseline_minutes=6 * 60,
    )

    def numbers(since: datetime, until: datetime) -> ProductionMonitoring:
        # Past windows have too few traces (< min_samples 10) to count.
        return _monitoring(n_traces=20 if until >= NOW else 3, n_errors=2)

    use_case, _, _ = _use_case([rule], _Monitoring(numbers))
    [result] = await use_case.execute(now=NOW)
    assert result.rule.state == "no_data"
    assert result.reading is not None and result.reading.baseline_windows == 0


@pytest.mark.asyncio
async def test_update_rederives_baseline_and_resets_state() -> None:
    rule = replace(
        AlertRule.create(
            PROJECT,
            name="lat",
            metric="latency_p90_ms",
            operator="gt",
            threshold=1000,
        ),
        state="firing",
        last_value=1500.0,
    )
    alerts = _Alerts([rule])

    async def _get(rule_id: uuid.UUID) -> AlertRule | None:
        return alerts.rules.get(rule_id)

    alerts.get_rule = _get  # type: ignore[attr-defined]
    manage = ManageAlertRules(alerts, _Projects(), None)  # type: ignore[arg-type]
    updated = await manage.update(
        rule.id, AlertRuleFields(condition="anomaly", threshold=3.0, operator="abs")
    )
    assert updated.condition == "anomaly"
    assert updated.baseline_minutes == 24 * 60
    assert updated.state == "no_data" and updated.last_value is None
    widened = await manage.update(rule.id, AlertRuleFields(window_minutes=120))
    assert widened.baseline_minutes == 48 * 60
    back = await manage.update(rule.id, AlertRuleFields(condition="threshold", operator="gt"))
    assert back.baseline_minutes is None


# --- API -------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_creates_and_evaluates_drift_rule(sqlite_client: AsyncClient) -> None:
    clear_baseline_cache()
    project = (
        await sqlite_client.post("/api/v1/projects", json={"name": "Drift", "slug": "drift-api"})
    ).json()
    created = await sqlite_client.post(
        f"/api/v1/projects/{project['id']}/alert-rules",
        json={
            "name": "Traffic drop",
            "metric": "traffic",
            "operator": "lt",
            "threshold": -0.5,
            "condition": "change",
            "baseline_minutes": 24 * 60,
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["condition"] == "change"
    assert body["baseline_minutes"] == 24 * 60

    bad = await sqlite_client.post(
        f"/api/v1/projects/{project['id']}/alert-rules",
        json={
            "name": "x",
            "metric": "traffic",
            "operator": "abs",
            "threshold": 1,
        },
    )
    assert bad.status_code == 400

    evaluated = await sqlite_client.post(f"/api/v1/projects/{project['id']}/alert-rules/evaluate")
    assert evaluated.status_code == 200
    [result] = evaluated.json()
    # No traffic at all: baseline 0 -> no data, not a 0% change.
    assert result["rule"]["state"] == "no_data"
    assert result["observed"] == 0
    assert result["baseline"] == 0

    patched = await sqlite_client.patch(
        f"/api/v1/alert-rules/{body['id']}",
        json={"condition": "anomaly", "operator": "abs", "threshold": 3},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["baseline_minutes"] == 24 * 60
