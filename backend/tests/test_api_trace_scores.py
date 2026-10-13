from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx2 import ASGITransport, AsyncClient

from aiobs_server.api.deps import (
    get_live_interaction_repository,
    get_project_repository,
    get_trace_repository,
    get_trace_score_repository,
)
from aiobs_server.domain.trace_score import MAX_TRACE_SCORE_BATCH
from aiobs_server.main import create_app
from support.repositories import InMemoryTraceScoreRepository
from test_api_evaluation import InMemoryTraceRepository
from test_api_live_interactions import InMemoryLiveRepository, InMemoryProjectRepository

TID = "ab" * 16


@dataclass
class Ctx:
    client: AsyncClient
    traces: InMemoryTraceRepository
    scores: InMemoryTraceScoreRepository
    live: InMemoryLiveRepository


@pytest.fixture
async def ctx() -> AsyncIterator[Ctx]:
    projects = InMemoryProjectRepository()
    traces = InMemoryTraceRepository()
    scores = InMemoryTraceScoreRepository()
    live = InMemoryLiveRepository()
    app = create_app()
    app.dependency_overrides[get_project_repository] = lambda: projects
    app.dependency_overrides[get_trace_repository] = lambda: traces
    app.dependency_overrides[get_trace_score_repository] = lambda: scores
    app.dependency_overrides[get_live_interaction_repository] = lambda: live
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield Ctx(client, traces, scores, live)
    app.dependency_overrides.clear()


async def _project(client: AsyncClient) -> str:
    resp = await client.post("/api/v1/projects", json={"name": f"p-{uuid.uuid4().hex[:6]}"})
    assert resp.status_code == 201, resp.text
    return str(resp.json()["id"])


async def _log(client: AsyncClient, project_id: str, scores: list[dict[str, Any]]) -> Any:
    return await client.post(f"/api/v1/projects/{project_id}/trace-scores", json={"scores": scores})


async def test_log_scores_computes_labels_and_upserts(ctx: Ctx) -> None:
    project_id = await _project(ctx.client)

    resp = await _log(
        ctx.client,
        project_id,
        [
            {"trace_id": TID.upper(), "name": "quality", "value": 0.4, "threshold": 0.5},
            {
                "trace_id": TID,
                "name": "user_feedback",
                "value": 0,
                "source": "human",
                "author": "u1",
            },
            {"trace_id": TID, "name": "cited", "value": 1.0, "label": "fail"},
        ],
    )
    assert resp.status_code == 202, resp.text
    assert resp.json() == {"accepted": 3}

    again = await _log(
        ctx.client,
        project_id,
        [{"trace_id": TID, "name": "quality", "value": 0.8, "threshold": 0.5}],
    )
    assert again.json() == {"accepted": 1}

    rows = (await ctx.scores.list_by_trace_ids(uuid.UUID(project_id), [TID]))[TID]
    assert [(r.name, r.value, r.label, r.author) for r in rows] == [
        ("cited", 1.0, "FAIL", None),  # an explicit FAIL label wins
        ("quality", 0.8, "PASS", None),  # re-logged: last write wins
        ("user_feedback", 0.0, "FAIL", "u1"),  # thumbs-down
    ]


@pytest.mark.parametrize(
    "item",
    [
        {"trace_id": "nothex", "name": "q", "value": 1.0},
        {"trace_id": TID, "name": "", "value": 1.0},
        {"trace_id": TID, "name": "x" * 201, "value": 1.0},
        {"trace_id": TID, "name": "q", "source": "bot"},
        {"trace_id": TID, "name": "q", "label": "MAYBE"},
        {"trace_id": TID, "name": "q", "value": "1"},
        {"trace_id": TID, "name": "q", "value": 10**400},
        {"trace_id": TID, "name": "q", "value": 1.0, "threshold": 10**400},
    ],
)
async def test_invalid_item_rejects_whole_batch(ctx: Ctx, item: dict[str, Any]) -> None:
    project_id = await _project(ctx.client)
    ok = {"trace_id": TID, "name": "fine", "value": 1.0}
    resp = await _log(ctx.client, project_id, [ok, item])
    assert resp.status_code == 422, resp.text
    assert await ctx.scores.list_by_trace_ids(uuid.UUID(project_id), [TID]) == {}


async def test_batch_limits_nan_and_unknown_project(ctx: Ctx) -> None:
    project_id = await _project(ctx.client)
    assert (await _log(ctx.client, project_id, [])).status_code == 422
    too_many = [
        {"trace_id": TID, "name": f"m{i}", "value": 1.0} for i in range(MAX_TRACE_SCORE_BATCH + 1)
    ]
    assert (await _log(ctx.client, project_id, too_many)).status_code == 422
    nan = await ctx.client.post(
        f"/api/v1/projects/{project_id}/trace-scores",
        content=f'{{"scores": [{{"trace_id": "{TID}", "name": "q", "value": NaN}}]}}'.encode(),
        headers={"content-type": "application/json"},
    )
    assert nan.status_code == 422, nan.text
    unknown = await _log(ctx.client, str(uuid.uuid4()), [{"trace_id": TID, "name": "q"}])
    assert unknown.status_code == 404, unknown.text


async def test_summary(ctx: Ctx) -> None:
    project_id = await _project(ctx.client)
    await _log(
        ctx.client,
        project_id,
        [
            {"trace_id": TID, "name": "quality", "value": 1.0, "threshold": 0.5},
            {"trace_id": "cd" * 16, "name": "quality", "value": 0.0, "threshold": 0.5},
            {"trace_id": TID, "name": "user_feedback", "value": 1, "source": "human"},
        ],
    )
    resp = await ctx.client.get(f"/api/v1/projects/{project_id}/trace-scores/summary")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["since"] < body["until"]
    assert body["rows"] == [
        {"name": "quality", "source": "sdk", "count": 2, "mean": 0.5, "pass_rate": 0.5},
        {"name": "user_feedback", "source": "human", "count": 1, "mean": 1.0, "pass_rate": 1.0},
    ]
    missing = await ctx.client.get(f"/api/v1/projects/{uuid.uuid4()}/trace-scores/summary")
    assert missing.status_code == 404
    reversed_window = await ctx.client.get(
        f"/api/v1/projects/{project_id}/trace-scores/summary",
        params={"since": "2026-10-14T10:00:00Z", "until": "2026-10-14T09:00:00Z"},
    )
    assert reversed_window.status_code == 400


async def test_error_label_is_kept(ctx: Ctx) -> None:
    project_id = await _project(ctx.client)
    resp = await _log(
        ctx.client,
        project_id,
        [{"trace_id": TID, "name": "q", "value": 0.1, "threshold": 0.5, "label": "error"}],
    )
    assert resp.status_code == 202, resp.text
    rows = (await ctx.scores.list_by_trace_ids(uuid.UUID(project_id), [TID]))[TID]
    assert [(r.name, r.label) for r in rows] == [("q", "ERROR")]


async def test_duplicate_keys_in_batch_last_wins(ctx: Ctx) -> None:
    project_id = await _project(ctx.client)
    resp = await _log(
        ctx.client,
        project_id,
        [
            {"trace_id": TID, "name": "q", "value": 0.1},
            {"trace_id": TID.upper(), "name": "q", "value": 0.9},
            {"trace_id": TID, "name": "other", "value": 1.0},
        ],
    )
    assert resp.json() == {"accepted": 2}
    rows = (await ctx.scores.list_by_trace_ids(uuid.UUID(project_id), [TID]))[TID]
    assert [(r.name, r.value) for r in rows] == [("other", 1.0), ("q", 0.9)]


async def test_summary_accepts_naive_datetimes_as_utc(ctx: Ctx) -> None:
    project_id = await _project(ctx.client)
    await _log(ctx.client, project_id, [{"trace_id": TID, "name": "q", "value": 1.0}])
    now = datetime.now(UTC).replace(tzinfo=None)
    resp = await ctx.client.get(
        f"/api/v1/projects/{project_id}/trace-scores/summary",
        params={
            "since": (now - timedelta(hours=1)).isoformat(),
            "until": (now + timedelta(hours=1)).isoformat(),
        },
    )
    assert resp.status_code == 200, resp.text
    assert [(r["name"], r["count"]) for r in resp.json()["rows"]] == [("q", 1)]
