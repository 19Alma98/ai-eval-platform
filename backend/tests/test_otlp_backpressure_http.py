"""HTTP-level OTLP backpressure (429/503 + Retry-After)."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from httpx2 import ASGITransport, AsyncClient

from opengrade_server.api.deps import (
    get_app_settings,
    get_live_interaction_repository,
    get_project_repository,
    get_trace_repository,
    get_trace_score_repository,
)
from opengrade_server.api.otlp_backpressure import reset_otlp_backpressure_for_tests
from opengrade_server.config import Settings, get_settings
from opengrade_server.domain.project import Project
from opengrade_server.main import create_app
from tests.support.repositories import InMemoryTraceScoreRepository
from tests.test_api_live_interactions import InMemoryLiveRepository
from tests.test_api_otlp import InMemoryProjectRepository, InMemoryTraceRepository


@pytest.fixture
async def otlp_limited_client() -> AsyncIterator[AsyncClient]:
    reset_otlp_backpressure_for_tests()
    get_settings.cache_clear()
    settings = Settings(
        otlp_rate_limit_per_second=1000.0,
        otlp_max_inflight=32,
        otlp_max_pending_scores=0,
        otlp_retry_after_seconds=7,
    )
    projects = InMemoryProjectRepository()
    project = Project(id=uuid.uuid4(), name="p", slug="p", created_at=datetime.now(UTC))
    await projects.add(project)
    traces = InMemoryTraceRepository()
    live = InMemoryLiveRepository()
    scores = InMemoryTraceScoreRepository()

    app = create_app(mount_packaged_ui=False)
    app.dependency_overrides[get_app_settings] = lambda: settings
    app.dependency_overrides[get_project_repository] = lambda: projects
    app.dependency_overrides[get_trace_repository] = lambda: traces
    app.dependency_overrides[get_live_interaction_repository] = lambda: live
    app.dependency_overrides[get_trace_score_repository] = lambda: scores

    # Force gate to rebuild with limited settings on first request
    reset_otlp_backpressure_for_tests()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.project_id = str(project.id)  # type: ignore[attr-defined]
        yield client

    app.dependency_overrides.clear()
    reset_otlp_backpressure_for_tests()
    get_settings.cache_clear()


def _minimal_otlp_json() -> bytes:
    payload = {
        "resourceSpans": [
            {
                "resource": {"attributes": []},
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                                "spanId": "bbbbbbbbbbbbbbbb",
                                "name": "test",
                                "kind": 1,
                                "startTimeUnixNano": "1",
                                "endTimeUnixNano": "2",
                                "attributes": [],
                            }
                        ]
                    }
                ],
            }
        ]
    }
    return json.dumps(payload).encode()


@pytest.mark.asyncio
async def test_otlp_503_when_pending_scores_at_cap(
    otlp_limited_client: AsyncClient,
) -> None:
    # max_pending_scores=0 → any request with inflight>=0 is rejected
    # live_score_inflight is 0, and 0 >= 0 → 503
    response = await otlp_limited_client.post(
        "/v1/traces",
        content=_minimal_otlp_json(),
        headers={
            "Content-Type": "application/json",
            "X-Project-Id": otlp_limited_client.project_id,  # type: ignore[attr-defined]
        },
    )
    assert response.status_code == 503
    assert response.headers.get("retry-after") == "7"
    assert "pending scores" in response.json()["detail"]


@pytest.mark.asyncio
async def test_otlp_429_when_rate_exceeded() -> None:
    reset_otlp_backpressure_for_tests()
    settings = Settings(
        otlp_rate_limit_per_second=1.0,
        otlp_max_inflight=32,
        otlp_max_pending_scores=100,
        otlp_retry_after_seconds=5,
    )
    # burst defaults to rate (1.0) → second request in same window → 429
    projects = InMemoryProjectRepository()
    project = Project(id=uuid.uuid4(), name="p", slug="p", created_at=datetime.now(UTC))
    await projects.add(project)

    app = create_app(mount_packaged_ui=False)
    app.dependency_overrides[get_app_settings] = lambda: settings
    app.dependency_overrides[get_project_repository] = lambda: projects
    app.dependency_overrides[get_trace_repository] = lambda: InMemoryTraceRepository()
    app.dependency_overrides[get_live_interaction_repository] = lambda: InMemoryLiveRepository()
    app.dependency_overrides[get_trace_score_repository] = lambda: InMemoryTraceScoreRepository()
    reset_otlp_backpressure_for_tests()

    transport = ASGITransport(app=app)
    body = _minimal_otlp_json()
    headers = {
        "Content-Type": "application/json",
        "X-Project-Id": str(project.id),
    }
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.post("/v1/traces", content=body, headers=headers)
        second = await client.post("/v1/traces", content=body, headers=headers)

    app.dependency_overrides.clear()
    reset_otlp_backpressure_for_tests()

    assert first.status_code == 200, first.text
    assert second.status_code == 429
    assert second.headers.get("retry-after") == "5"
