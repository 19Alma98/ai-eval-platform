from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient

from aiobs.api.deps import get_project_repository, get_trace_repository
from aiobs.domain.project import Project
from aiobs.domain.trace import Trace
from aiobs.main import create_app


class InMemoryProjectRepository:
    def __init__(self) -> None:
        self._projects: dict[uuid.UUID, Project] = {}

    async def add(self, project: Project) -> Project:
        self._projects[project.id] = project
        return project

    async def get_by_id(self, project_id: uuid.UUID) -> Project | None:
        return self._projects.get(project_id)

    async def get_by_slug(self, slug: str) -> Project | None:
        for project in self._projects.values():
            if project.slug == slug:
                return project
        return None

    async def list_all(self) -> list[Project]:
        return sorted(
            self._projects.values(),
            key=lambda project: project.created_at or datetime.now(UTC),
            reverse=True,
        )


class InMemoryTraceRepository:
    def __init__(self) -> None:
        self._traces: dict[tuple[uuid.UUID, str], Trace] = {}

    async def upsert(self, trace: Trace) -> Trace:
        key = (trace.project_id, trace.trace_id)
        self._traces[key] = trace
        return trace

    async def get_by_trace_id(self, project_id: uuid.UUID, trace_id: str) -> Trace | None:
        return self._traces.get((project_id, trace_id))

    async def list_by_project(
        self,
        project_id: uuid.UUID,
        *,
        status: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        cursor_start_time: datetime | None = None,
        cursor_id: uuid.UUID | None = None,
        limit: int = 50,
    ) -> list[Trace]:
        items = [t for (pid, _), t in self._traces.items() if pid == project_id]
        if status is not None:
            items = [t for t in items if t.status == status]
        if start_time is not None:
            items = [t for t in items if t.start_time >= start_time]
        if end_time is not None:
            items = [t for t in items if t.start_time <= end_time]
        items.sort(key=lambda t: (t.start_time, t.id), reverse=True)
        if cursor_start_time is not None and cursor_id is not None:
            items = [t for t in items if (t.start_time, t.id) < (cursor_start_time, cursor_id)]
        result: list[Trace] = []
        for t in items[:limit]:
            meta = {**t.metadata, "_span_count": len(t.spans)}
            result.append(
                Trace(
                    id=t.id,
                    project_id=t.project_id,
                    trace_id=t.trace_id,
                    name=t.name,
                    status=t.status,
                    start_time=t.start_time,
                    end_time=t.end_time,
                    input=t.input,
                    output=t.output,
                    metadata=meta,
                    environment=t.environment,
                    user_id=t.user_id,
                    session_id=t.session_id,
                    spans=(),
                )
            )
        return result


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    import os

    from aiobs.config import get_settings

    # Assert redaction path; ignore local .env CONTENT_CAPTURE_ENABLED=true.
    os.environ["CONTENT_CAPTURE_ENABLED"] = "false"
    get_settings.cache_clear()

    projects = InMemoryProjectRepository()
    traces = InMemoryTraceRepository()
    app = create_app()
    app.dependency_overrides[get_project_repository] = lambda: projects
    app.dependency_overrides[get_trace_repository] = lambda: traces

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
    os.environ.pop("CONTENT_CAPTURE_ENABLED", None)
    get_settings.cache_clear()


async def _create_project(client: AsyncClient) -> dict:
    response = await client.post("/api/v1/projects", json={"name": "Demo", "slug": "demo"})
    assert response.status_code == 201
    return response.json()


@pytest.mark.asyncio
async def test_otlp_json_ingest_and_get(client: AsyncClient) -> None:
    project = await _create_project(client)
    project_id = project["id"]
    payload = {
        "resourceSpans": [
            {
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": "aa" * 16,
                                "spanId": "bb" * 8,
                                "name": "chain",
                                "startTimeUnixNano": "1700000000000000000",
                                "endTimeUnixNano": "1700000001000000000",
                                "status": {"code": "STATUS_CODE_OK"},
                                "attributes": [
                                    {
                                        "key": "openinference.span.kind",
                                        "value": {"stringValue": "CHAIN"},
                                    },
                                    {
                                        "key": "input.value",
                                        "value": {"stringValue": "secret"},
                                    },
                                ],
                            }
                        ]
                    }
                ]
            }
        ]
    }
    otlp = await client.post(
        "/v1/traces",
        content=json.dumps(payload),
        headers={
            "content-type": "application/json",
            "X-Project-Id": project_id,
        },
    )
    assert otlp.status_code == 200

    detail = await client.get(f"/api/v1/projects/{project_id}/traces/{'aa' * 16}")
    assert detail.status_code == 200
    detail_body = detail.json()
    assert detail_body["trace_id"] == "aa" * 16
    assert detail_body["spans"][0]["kind"] == "CHAIN"
    assert "input.value" not in detail_body["spans"][0]["attributes"]

    listed = await client.get(f"/api/v1/projects/{project_id}/traces")
    assert listed.status_code == 404


@pytest.mark.asyncio
async def test_otlp_requires_project_header(client: AsyncClient) -> None:
    await _create_project(client)
    response = await client.post(
        "/v1/traces",
        content=b"{}",
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_otlp_unknown_project(client: AsyncClient) -> None:
    response = await client.post(
        "/v1/traces",
        content=b'{"resourceSpans":[]}',
        headers={
            "content-type": "application/json",
            "X-Project-Id": str(uuid.uuid4()),
        },
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_rest_create_trace_rejected(client: AsyncClient) -> None:
    project = await _create_project(client)
    project_id = project["id"]
    create = await client.post(
        f"/api/v1/projects/{project_id}/traces",
        json={
            "trace_id": "cc" * 16,
            "name": "manual",
            "status": "ok",
            "start_time": "2026-01-01T00:00:00Z",
            "end_time": "2026-01-01T00:00:01Z",
            "spans": [
                {
                    "span_id": "dd" * 8,
                    "name": "llm",
                    "kind": "LLM",
                    "start_time": "2026-01-01T00:00:00Z",
                    "end_time": "2026-01-01T00:00:01Z",
                    "status": "ok",
                    "attributes": {"gen_ai.input.messages": [{"role": "user", "content": "x"}]},
                }
            ],
        },
    )
    assert create.status_code == 404
