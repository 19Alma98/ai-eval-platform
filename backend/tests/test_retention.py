"""Retention: old production data is purged, evaluation data is kept."""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx2 import AsyncClient

import test_sqlite_smoke
from opengrade_server.application.retention import PurgeProductionData
from opengrade_server.infrastructure.db import get_session_factory
from opengrade_server.infrastructure.repositories import (
    SqlAlchemyProjectRepository,
    SqlAlchemyRetentionRepository,
)
from support import postgres as postgres_support

sqlite_client = test_sqlite_smoke.sqlite_client
pg_client = postgres_support.client


def _span(trace_id: str, *, age_days: float, attrs: dict[str, str] | None = None) -> dict[str, Any]:
    end = time.time_ns() - int(age_days * 86400 * 1e9)
    attributes = [{"key": "openinference.span.kind", "value": {"stringValue": "CHAIN"}}]
    attributes += [{"key": k, "value": {"stringValue": v}} for k, v in (attrs or {}).items()]
    return {
        "traceId": trace_id,
        "spanId": trace_id[:16],
        "name": "answer",
        "startTimeUnixNano": str(end - 10_000_000),
        "endTimeUnixNano": str(end),
        "status": {"code": "STATUS_CODE_OK"},
        "attributes": attributes,
    }


async def _purge(project_id: str, *, dry_run: bool, days_ahead: int = 0) -> Any:
    async with get_session_factory()() as session:
        use_case = PurgeProductionData(
            SqlAlchemyProjectRepository(session), SqlAlchemyRetentionRepository(session)
        )
        return await use_case.execute(
            uuid.UUID(project_id),
            dry_run=dry_run,
            now=datetime.now(UTC) + timedelta(days=days_ahead),
        )


@pytest.mark.asyncio
async def test_retention_purges_production_and_keeps_eval_data(
    sqlite_client: AsyncClient,
) -> None:
    project = (
        await sqlite_client.post("/api/v1/projects", json={"name": "Ret", "slug": "ret"})
    ).json()
    pid = project["id"]
    base = f"/api/v1/projects/{pid}"

    # Evaluation side: a dataset item built from a trace, and an experiment-bound trace.
    linked, bound, old, recent = (uuid.uuid4().hex for _ in range(4))
    dataset = (
        await sqlite_client.post(
            f"{base}/datasets", json={"name": "gold", "task_type": "classification"}
        )
    ).json()
    item = (
        await sqlite_client.post(
            f"/api/v1/datasets/{dataset['id']}/items",
            json={"input": "q", "expected_output": "a", "source_trace_id": linked},
        )
    ).json()
    experiment = (
        await sqlite_client.post(
            f"{base}/experiments", json={"name": "e", "dataset_id": dataset["id"]}
        )
    ).json()
    spans = [
        _span(linked, age_days=40),
        _span(
            bound,
            age_days=40,
            attrs={
                "opengrade.experiment_id": experiment["id"],
                "opengrade.dataset_item_id": item["id"],
            },
        ),
        _span(old, age_days=40),
        _span(recent, age_days=0),
    ]
    ingest = await sqlite_client.post(
        "/v1/traces",
        headers={"X-Project-Slug": "ret"},
        json={"resourceSpans": [{"scopeSpans": [{"spans": spans}]}]},
    )
    assert ingest.status_code == 200, ingest.text

    # Without a retention period nothing is purged.
    status = (await sqlite_client.get(f"{base}/retention")).json()
    assert status["effective_days"] is None
    assert status["pending"]["traces"] == 0

    bad = await sqlite_client.put(f"{base}/retention", json={"retention_days": 0})
    assert bad.status_code == 422
    status = (await sqlite_client.put(f"{base}/retention", json={"retention_days": 30})).json()
    assert status["retention_days"] == 30
    assert status["effective_days"] == 30
    assert status["pending"]["traces"] == 1
    assert status["pending"]["traces_kept"] == 2
    assert (await sqlite_client.get(f"{base}")).json()["retention_days"] == 30

    purged = (await sqlite_client.post(f"{base}/retention/purge")).json()
    assert purged["traces"] == 1
    assert purged["dry_run"] is False
    remaining = {t["trace_id"] for t in (await sqlite_client.get(f"{base}/traces")).json()["items"]}
    assert remaining == {linked, bound, recent}

    # Rows the API stamps "now": purge as if 40 days had passed.
    await sqlite_client.post(
        f"{base}/live-interactions", json={"question": "q", "answer": "a", "documents": []}
    )
    scored = await sqlite_client.post(
        f"{base}/trace-scores", json={"scores": [{"trace_id": recent, "name": "x", "value": 1}]}
    )
    assert scored.status_code == 202, scored.text
    rule = (
        await sqlite_client.post(
            f"{base}/alert-rules",
            json={"name": "q", "metric": "traffic", "operator": "lt", "threshold": 1000},
        )
    ).json()
    await sqlite_client.post(f"/api/v1/alert-rules/{rule['id']}/test")

    preview = await _purge(pid, dry_run=True, days_ahead=40)
    assert preview.traces == 1  # recent (linked and bound stay)
    assert preview.rows == {"live_interactions": 1, "trace_scores": 1, "alert_events": 1}
    report = await _purge(pid, dry_run=False, days_ahead=40)
    assert report.rows == preview.rows
    assert (await sqlite_client.get(f"{base}/alert-events")).json() == []
    live = (await sqlite_client.get(f"{base}/live-interactions")).json()
    assert live["items"] == []

    cleared = (await sqlite_client.put(f"{base}/retention", json={"retention_days": None})).json()
    assert cleared["effective_days"] is None


@pytest.mark.asyncio
async def test_retention_on_postgres(pg_client: AsyncClient) -> None:
    await test_retention_purges_production_and_keeps_eval_data(pg_client)
