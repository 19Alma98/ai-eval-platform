"""Server-side alert rules: evaluation, state transitions, webhook delivery."""

from __future__ import annotations

import asyncio
import json
import threading
import time
import uuid
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest
from httpx2 import AsyncClient

import test_sqlite_smoke
from opengrade_server.application.alerts import (
    MetricReading,
    alert_message,
    next_state,
    notification_kind,
    read_metric,
)
from opengrade_server.application.monitoring import (
    LatencyPercentiles,
    MetricMonitor,
    ProductionMonitoring,
)
from opengrade_server.domain.alert import AlertRule, AlertRuleValidationError

sqlite_client = test_sqlite_smoke.sqlite_client

PROJECT = uuid.uuid4()


def _monitoring(**overrides: Any) -> ProductionMonitoring:
    now = datetime.now(UTC)
    base: dict[str, Any] = {
        "since": now - timedelta(hours=1),
        "until": now,
        "bucket_seconds": 300,
        "n_traces": 20,
        "n_errors": 5,
        "latency": LatencyPercentiles(p50_ms=100.0, p90_ms=400.0, p99_ms=900.0),
        "prompt_tokens": 0.0,
        "completion_tokens": 0.0,
        "total_tokens": 1000.0,
        "cost_usd": 0.5,
        "traces_truncated": False,
        "n_needs_review": 3,
        "traffic": [],
        "metrics": [],
    }
    base.update(overrides)
    return ProductionMonitoring(**base)


def _score(name: str, source: str, n: int, mean: float, fail_rate: float) -> MetricMonitor:
    return MetricMonitor(
        name=name,
        source=source,
        n=n,
        mean=mean,
        fail_rate=fail_rate,
        threshold=None,
        histogram_edges=[],
        histogram_counts=[],
        series=[],
    )


def test_read_metric_covers_traffic_latency_and_scores() -> None:
    m = _monitoring(
        metrics=[
            _score("groundedness", "judge", 10, 0.8, 0.1),
            _score("groundedness", "sdk", 30, 0.4, 0.5),
        ]
    )
    rule = AlertRule.create(PROJECT, name="e", metric="error_rate", operator="gt", threshold=0.1)
    assert read_metric(rule, m) == MetricReading(0.25, 20)
    p99 = replace(rule, metric="latency_p99_ms")
    assert read_metric(p99, m).value == 900.0
    pooled = AlertRule.create(
        PROJECT,
        name="g",
        metric="score_fail_rate",
        operator="gt",
        threshold=0.2,
        score_name="groundedness",
    )
    reading = read_metric(pooled, m)
    assert reading.samples == 40
    assert reading.value == pytest.approx((0.1 * 10 + 0.5 * 30) / 40)
    judge_only = replace(pooled, score_source="judge")
    assert read_metric(judge_only, m) == MetricReading(0.1, 10)
    missing = replace(pooled, score_name="nope")
    assert read_metric(missing, m) == MetricReading(None, 0)


def test_state_transitions_fire_once_resolve_once_and_repeat() -> None:
    rule = AlertRule.create(
        PROJECT, name="e", metric="error_rate", operator="gt", threshold=0.1, repeat_minutes=30
    )
    now = datetime.now(UTC)
    assert next_state(rule, MetricReading(0.5, 5)) == "no_data"  # under min_samples (10)
    assert next_state(rule, MetricReading(0.5, 20)) == "firing"
    assert notification_kind(rule, "firing", now) == "firing"
    firing = replace(rule, state="firing", last_notified_at=now)
    assert notification_kind(firing, "firing", now + timedelta(minutes=5)) is None
    assert notification_kind(firing, "firing", now + timedelta(minutes=31)) == "repeat"
    assert notification_kind(firing, "ok", now) == "resolved"
    assert notification_kind(replace(rule, state="ok"), "ok", now) is None
    assert notification_kind(firing, "no_data", now) is None


def test_message_and_validation() -> None:
    rule = AlertRule.create(
        PROJECT,
        name="Grounding",
        metric="score_fail_rate",
        operator="gt",
        threshold=0.2,
        score_name="groundedness",
        score_source="judge",
        window_minutes=120,
    )
    text = alert_message(rule, "firing", 0.35, "shop")
    assert text == (
        "[OpenGrade] FIRING shop / Grounding: groundedness (judge) fail rate 35.0% "
        "(alert when > 20.0%, last 2 hours)"
    )
    with pytest.raises(AlertRuleValidationError, match="needs score_name"):
        AlertRule.create(PROJECT, name="x", metric="score_mean", operator="lt", threshold=0.5)
    with pytest.raises(AlertRuleValidationError, match="http"):
        AlertRule.create(
            PROJECT,
            name="x",
            metric="traffic",
            operator="lt",
            threshold=1,
            webhook_url="ftp://x",
        )
    traffic = AlertRule.create(PROJECT, name="t", metric="traffic", operator="lt", threshold=1)
    assert traffic.min_samples == 0


class _Receiver(BaseHTTPRequestHandler):
    received: list[dict[str, Any]] = []
    status = 200

    def do_POST(self) -> None:  # noqa: N802 — http.server API
        length = int(self.headers.get("content-length", 0))
        type(self).received.append(json.loads(self.rfile.read(length)))
        self.send_response(type(self).status)
        self.end_headers()

    def log_message(self, *args: object) -> None:
        return None


@pytest.fixture
def webhook() -> Iterator[tuple[str, type[_Receiver]]]:
    _Receiver.received = []
    _Receiver.status = 200
    server = HTTPServer(("127.0.0.1", 0), _Receiver)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/hook", _Receiver
    server.shutdown()


def _span(trace_id: str, error: bool) -> dict[str, Any]:
    now = time.time_ns()
    return {
        "traceId": trace_id,
        "spanId": trace_id[:16],
        "name": "answer",
        "startTimeUnixNano": str(now - 50_000_000),
        "endTimeUnixNano": str(now),
        "status": {"code": "STATUS_CODE_ERROR" if error else "STATUS_CODE_OK"},
        "attributes": [{"key": "openinference.span.kind", "value": {"stringValue": "CHAIN"}}],
    }


async def _ingest(client: AsyncClient, slug: str, *, ok: int, errors: int) -> None:
    spans = [_span(uuid.uuid4().hex, error=i < errors) for i in range(ok + errors)]
    resp = await client.post(
        "/v1/traces",
        headers={"X-Project-Slug": slug},
        json={"resourceSpans": [{"scopeSpans": [{"spans": spans}]}]},
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_rule_fires_notifies_and_resolves(
    sqlite_client: AsyncClient, webhook: tuple[str, type[_Receiver]]
) -> None:
    url, receiver = webhook
    project = (
        await sqlite_client.post("/api/v1/projects", json={"name": "Alerts", "slug": "alerts"})
    ).json()
    base = f"/api/v1/projects/{project['id']}"
    created = await sqlite_client.post(
        f"{base}/alert-rules",
        json={
            "name": "Errors",
            "metric": "error_rate",
            "threshold": 0.2,
            "min_samples": 4,
            "webhook_url": url,
        },
    )
    assert created.status_code == 201, created.text
    rule = created.json()
    assert rule["state"] == "no_data"

    await _ingest(sqlite_client, "alerts", ok=3, errors=3)
    (first,) = (await sqlite_client.post(f"{base}/alert-rules/evaluate")).json()
    assert first["rule"]["state"] == "firing"
    assert first["value"] == pytest.approx(0.5)
    assert first["event"]["kind"] == "firing"
    assert first["event"]["delivery_status"] == "sent"
    (payload,) = receiver.received
    assert payload["event"] == "firing"
    assert payload["value"] == pytest.approx(0.5)
    assert "FIRING Alerts / Errors: error rate 50.0%" in payload["text"]

    (again,) = (await sqlite_client.post(f"{base}/alert-rules/evaluate")).json()
    assert again["event"] is None
    assert len(receiver.received) == 1

    await _ingest(sqlite_client, "alerts", ok=30, errors=0)
    (resolved,) = (await sqlite_client.post(f"{base}/alert-rules/evaluate")).json()
    assert resolved["rule"]["state"] == "ok"
    assert resolved["event"]["kind"] == "resolved"
    assert receiver.received[-1]["event"] == "resolved"

    events = (await sqlite_client.get(f"{base}/alert-events")).json()
    assert [e["kind"] for e in events] == ["resolved", "firing"]


@pytest.mark.asyncio
async def test_slack_format_failed_delivery_and_crud(
    sqlite_client: AsyncClient, webhook: tuple[str, type[_Receiver]]
) -> None:
    url, receiver = webhook
    project = (await sqlite_client.post("/api/v1/projects", json={"name": "Crud"})).json()
    base = f"/api/v1/projects/{project['id']}"
    rule = (
        await sqlite_client.post(
            f"{base}/alert-rules",
            json={
                "name": "Quiet",
                "metric": "traffic",
                "operator": "lt",
                "threshold": 1,
                "webhook_url": url,
                "webhook_format": "slack",
            },
        )
    ).json()
    assert rule["min_samples"] == 0

    test = await sqlite_client.post(f"/api/v1/alert-rules/{rule['id']}/test")
    assert test.status_code == 200, test.text
    assert test.json()["kind"] == "test"
    assert set(receiver.received[-1]) == {"text"}

    receiver.status = 500
    (fired,) = (await sqlite_client.post(f"{base}/alert-rules/evaluate")).json()
    assert fired["event"]["kind"] == "firing"
    assert fired["event"]["delivery_status"] == "failed"
    assert "HTTP 500" in fired["event"]["delivery_error"]

    patched = await sqlite_client.patch(
        f"/api/v1/alert-rules/{rule['id']}", json={"threshold": 0, "webhook_url": None}
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["webhook_url"] is None
    assert patched.json()["state"] == "no_data"  # condition changed: state starts over

    bad = await sqlite_client.patch(
        f"/api/v1/alert-rules/{rule['id']}", json={"metric": "score_mean"}
    )
    assert bad.status_code == 400
    invalid = await sqlite_client.post(
        f"{base}/alert-rules", json={"name": "x", "metric": "nope", "threshold": 1}
    )
    assert invalid.status_code == 422

    listed = (await sqlite_client.get(f"{base}/alert-rules")).json()
    assert [r["name"] for r in listed] == ["Quiet"]
    deleted = await sqlite_client.delete(f"/api/v1/alert-rules/{rule['id']}")
    assert deleted.status_code == 204
    assert (await sqlite_client.get(f"/api/v1/alert-rules/{rule['id']}")).status_code == 404


@pytest.mark.asyncio
async def test_background_loop_evaluates_rules(sqlite_client: AsyncClient) -> None:
    from opengrade_server.application.alerts import run_alert_loop

    project = (await sqlite_client.post("/api/v1/projects", json={"name": "Loop"})).json()
    rule = (
        await sqlite_client.post(
            f"/api/v1/projects/{project['id']}/alert-rules",
            json={"name": "Quiet", "metric": "traffic", "operator": "lt", "threshold": 1},
        )
    ).json()
    task = asyncio.create_task(run_alert_loop(0.05))
    try:
        for _ in range(100):
            current = (await sqlite_client.get(f"/api/v1/alert-rules/{rule['id']}")).json()
            if current["last_evaluated_at"] is not None:
                break
            await asyncio.sleep(0.05)
    finally:
        task.cancel()
    assert current["state"] == "firing"
    events = (await sqlite_client.get(f"/api/v1/projects/{project['id']}/alert-events")).json()
    assert events[0]["delivery_status"] == "skipped"
