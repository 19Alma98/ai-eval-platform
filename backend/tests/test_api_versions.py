"""Release (service.version) and environment on traces: ingest, filter, compare, alert."""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx2 import AsyncClient

import test_sqlite_smoke

sqlite_client = test_sqlite_smoke.sqlite_client


def _resource_spans(version: str, environment: str, *, ok: int, errors: int) -> dict[str, Any]:
    now = time.time_ns()
    spans = []
    for i in range(ok + errors):
        trace_id = uuid.uuid4().hex
        spans.append(
            {
                "traceId": trace_id,
                "spanId": trace_id[:16],
                "name": "answer",
                "startTimeUnixNano": str(now - 100_000_000),
                "endTimeUnixNano": str(now),
                "status": {"code": "STATUS_CODE_ERROR" if i < errors else "STATUS_CODE_OK"},
                "attributes": [
                    {"key": "openinference.span.kind", "value": {"stringValue": "CHAIN"}}
                ],
            }
        )
    return {
        "resource": {
            "attributes": [
                {"key": "service.name", "value": {"stringValue": "rag"}},
                {"key": "service.version", "value": {"stringValue": version}},
                {"key": "deployment.environment", "value": {"stringValue": environment}},
            ]
        },
        "scopeSpans": [{"spans": spans}],
    }


@pytest.mark.asyncio
async def test_version_and_environment_filters(sqlite_client: AsyncClient) -> None:
    project = (
        await sqlite_client.post("/api/v1/projects", json={"name": "Rel", "slug": "rel"})
    ).json()
    resp = await sqlite_client.post(
        "/v1/traces",
        headers={"X-Project-Slug": "rel"},
        json={
            "resourceSpans": [
                _resource_spans("v1", "prod", ok=8, errors=0),
                _resource_spans("v2", "prod", ok=2, errors=2),
                _resource_spans("v2", "staging", ok=3, errors=0),
            ]
        },
    )
    assert resp.status_code == 200, resp.text
    base = f"/api/v1/projects/{project['id']}"
    since = (datetime.now(UTC) - timedelta(hours=1)).isoformat()

    traces = (await sqlite_client.get(f"{base}/traces", params={"version": "v2"})).json()
    assert len(traces["items"]) == 7
    assert {t["version"] for t in traces["items"]} == {"v2"}
    prod_v2 = (
        await sqlite_client.get(f"{base}/traces", params={"version": "v2", "environment": "prod"})
    ).json()
    assert len(prod_v2["items"]) == 4

    facets = (await sqlite_client.get(f"{base}/monitoring/facets", params={"since": since})).json()
    assert facets["versions"] == [
        {"value": "v1", "n_traces": 8},
        {"value": "v2", "n_traces": 7},
    ]
    assert {f["value"] for f in facets["environments"]} == {"prod", "staging"}

    filtered = (
        await sqlite_client.get(
            f"{base}/monitoring", params={"since": since, "version": "v2", "environment": "prod"}
        )
    ).json()
    assert filtered["n_traces"] == 4
    assert filtered["n_errors"] == 2

    versions = (
        await sqlite_client.get(
            f"{base}/monitoring/versions", params={"since": since, "environment": "prod"}
        )
    ).json()
    by_version = {v["version"]: v for v in versions}
    assert by_version["v1"]["error_rate"] == 0
    assert by_version["v2"]["error_rate"] == pytest.approx(0.5)
    assert by_version["v2"]["n_traces"] == 4

    rule = (
        await sqlite_client.post(
            f"{base}/alert-rules",
            json={
                "name": "v2 prod errors",
                "metric": "error_rate",
                "threshold": 0.2,
                "min_samples": 1,
                "environment": "prod",
                "version": "v2",
            },
        )
    ).json()
    assert rule["environment"] == "prod"
    (result,) = (await sqlite_client.post(f"{base}/alert-rules/evaluate")).json()
    assert result["value"] == pytest.approx(0.5)
    assert result["rule"]["state"] == "firing"
    assert "[env prod, version v2]" in result["event"]["message"]

    cleared = await sqlite_client.patch(f"/api/v1/alert-rules/{rule['id']}", json={"version": None})
    assert cleared.json()["version"] is None
    (all_prod,) = (await sqlite_client.post(f"{base}/alert-rules/evaluate")).json()
    assert all_prod["value"] == pytest.approx(2 / 12)
