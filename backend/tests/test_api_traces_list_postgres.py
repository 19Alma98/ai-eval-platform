from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx2 import AsyncClient

pytestmark = pytest.mark.integration


def _nanos(ts: datetime) -> str:
    return str(int(ts.timestamp() * 1_000_000_000))


def _attr(key: str, value: Any) -> dict[str, Any]:
    if isinstance(value, int):
        return {"key": key, "value": {"intValue": str(value)}}
    if isinstance(value, float):
        return {"key": key, "value": {"doubleValue": value}}
    return {"key": key, "value": {"stringValue": value}}


def _span(
    trace_id: str, span_id: str, name: str, start: datetime, ms: int, *, error: bool = False
) -> dict[str, Any]:
    return {
        "traceId": trace_id,
        "spanId": span_id,
        "name": name,
        "startTimeUnixNano": _nanos(start),
        "endTimeUnixNano": _nanos(start + timedelta(milliseconds=ms)),
        "status": {"code": "STATUS_CODE_ERROR" if error else "STATUS_CODE_OK"},
        "attributes": [
            _attr("openinference.span.kind", "LLM"),
            _attr("gen_ai.usage.input_tokens", 50),
            _attr("gen_ai.usage.output_tokens", 10),
            _attr("gen_ai.usage.cost", 0.002),
        ],
    }


async def _ingest(client: AsyncClient, project_id: str, spans: list[dict[str, Any]]) -> None:
    resp = await client.post(
        "/v1/traces",
        json={"resourceSpans": [{"scopeSpans": [{"spans": spans}]}]},
        headers={"X-Project-Id": project_id},
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_list_search_paginate_and_link_live(client: AsyncClient) -> None:
    project = await client.post("/api/v1/projects", json={"name": "Trace List"})
    project_id = project.json()["id"]
    now = datetime.now(UTC).replace(microsecond=0)
    ids = [f"{i:02x}" * 16 for i in (1, 2, 3)]
    await _ingest(
        client,
        project_id,
        [
            _span(ids[0], "a1" * 8, "retrieve_answer", now - timedelta(minutes=3), 200),
            _span(ids[1], "b1" * 8, "summarize", now - timedelta(minutes=2), 400, error=True),
            _span(ids[2], "c1" * 8, "retrieve_answer", now - timedelta(minutes=1), 600),
        ],
    )
    live = await client.post(
        f"/api/v1/projects/{project_id}/live-interactions",
        json={"question": "q?", "answer": "a.", "external_id": f"trace:{ids[2]}"},
    )
    assert live.status_code == 202, live.text

    base = f"/api/v1/projects/{project_id}/traces"
    first = (await client.get(base, params={"limit": 2})).json()
    assert [t["trace_id"] for t in first["items"]] == [ids[2], ids[1]]
    assert first["items"][0]["duration_ms"] == pytest.approx(600.0)
    assert first["items"][0]["live_interaction_id"] == live.json()["id"]
    assert first["items"][1]["live_interaction_id"] is None
    assert first["next_cursor"]

    second = (await client.get(base, params={"limit": 2, "cursor": first["next_cursor"]})).json()
    assert [t["trace_id"] for t in second["items"]] == [ids[0]]
    assert second["next_cursor"] is None

    searched = (await client.get(base, params={"search": "retrieve"})).json()
    assert {t["trace_id"] for t in searched["items"]} == {ids[0], ids[2]}
    errors = (await client.get(base, params={"status": "error"})).json()
    assert [t["trace_id"] for t in errors["items"]] == [ids[1]]

    assert (await client.get(base, params={"status": "nope"})).status_code == 422
    assert (await client.get(base, params={"cursor": "!!"})).status_code == 400

    detail = (await client.get(f"{base}/{ids[2]}")).json()
    assert detail["live_interaction_id"] == live.json()["id"]

    since = (now - timedelta(minutes=10)).isoformat()
    monitoring = await client.get(
        f"/api/v1/projects/{project_id}/monitoring", params={"since": since}
    )
    assert monitoring.status_code == 200, monitoring.text
    body = monitoring.json()
    assert body["n_traces"] == 3
    assert body["n_errors"] == 1
    assert body["total_tokens"] == pytest.approx(180.0)
    assert body["latency"]["p50_ms"] == pytest.approx(400.0)
    assert sum(b["n_traces"] for b in body["traffic"]) == 3


@pytest.mark.asyncio
async def test_experiment_summaries_for_project(client: AsyncClient) -> None:
    project = await client.post("/api/v1/projects", json={"name": "Summaries"})
    project_id = project.json()["id"]
    dataset = await client.post(
        f"/api/v1/projects/{project_id}/datasets", json={"name": "ds", "task_type": None}
    )
    assert dataset.status_code == 201, dataset.text
    created = []
    for name in ("v1", "v2"):
        exp = await client.post(
            f"/api/v1/projects/{project_id}/experiments",
            json={"name": name, "dataset_id": dataset.json()["id"]},
        )
        assert exp.status_code == 201, exp.text
        created.append(exp.json()["id"])

    all_rows = await client.get(f"/api/v1/projects/{project_id}/experiments/summaries")
    assert all_rows.status_code == 200, all_rows.text
    assert {r["experiment_id"] for r in all_rows.json()} == set(created)

    one = await client.get(
        f"/api/v1/projects/{project_id}/experiments/summaries",
        params={"experiment_ids": created[0]},
    )
    assert [r["experiment_id"] for r in one.json()] == [created[0]]
    assert one.json()[0]["evaluators"] == []
