from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from httpx2 import ASGITransport, AsyncClient

from opengrade_server.api.deps import get_production_monitoring, get_project_repository
from opengrade_server.application.monitoring import (
    LatencyPercentiles,
    ProductionMonitoring,
)
from opengrade_server.main import create_app
from tests.test_api_live_interactions import InMemoryProjectRepository


class _StubMonitoring:
    async def execute(
        self,
        project_id: uuid.UUID,
        *,
        since: datetime,
        until: datetime | None = None,
    ) -> ProductionMonitoring:
        end = until or datetime.now(tz=UTC)
        empty_latency = LatencyPercentiles(p50_ms=None, p90_ms=None, p99_ms=None)
        return ProductionMonitoring(
            since=since,
            until=end,
            bucket_seconds=300,
            n_traces=0,
            n_errors=0,
            latency=empty_latency,
            prompt_tokens=0.0,
            completion_tokens=0.0,
            total_tokens=0.0,
            cost_usd=0.0,
            traces_truncated=False,
            n_needs_review=0,
            traffic=[],
            metrics=[],
        )


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    projects = InMemoryProjectRepository()
    app = create_app()
    app.dependency_overrides[get_project_repository] = lambda: projects
    app.dependency_overrides[get_production_monitoring] = lambda: _StubMonitoring()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def _project(client: AsyncClient) -> str:
    response = await client.post("/api/v1/projects", json={"name": "Mon", "slug": "mon"})
    assert response.status_code == 201
    return response.json()["id"]


@pytest.mark.asyncio
async def test_monitoring_accepts_mixed_naive_and_aware_datetimes(client: AsyncClient) -> None:
    project_id = await _project(client)
    since = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    until = datetime(2026, 1, 1, 13, 0, 0)  # naive
    resp = await client.get(
        f"/api/v1/projects/{project_id}/monitoring",
        params={"since": since.isoformat().replace("+00:00", "Z"), "until": until.isoformat()},
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_monitoring_rejects_until_before_since_without_500(client: AsyncClient) -> None:
    project_id = await _project(client)
    since = datetime(2026, 1, 1, 13, 0, 0, tzinfo=UTC)
    until = datetime(2026, 1, 1, 12, 0, 0)  # naive, earlier
    resp = await client.get(
        f"/api/v1/projects/{project_id}/monitoring",
        params={"since": since.isoformat().replace("+00:00", "Z"), "until": until.isoformat()},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "until must be after since"


@pytest.mark.asyncio
async def test_monitoring_accepts_naive_pair_as_utc(client: AsyncClient) -> None:
    project_id = await _project(client)
    now = datetime.now(UTC).replace(tzinfo=None)
    resp = await client.get(
        f"/api/v1/projects/{project_id}/monitoring",
        params={
            "since": (now - timedelta(hours=1)).isoformat(),
            "until": (now + timedelta(hours=1)).isoformat(),
        },
    )
    assert resp.status_code == 200, resp.text
