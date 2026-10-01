from __future__ import annotations

import base64
import json
import uuid
from dataclasses import dataclass
from datetime import datetime

from aiobs.domain.repositories import ProjectRepository, TraceRepository
from aiobs.domain.trace import Trace


class TraceNotFoundError(Exception):
    def __init__(self, project_id: uuid.UUID, trace_id: str) -> None:
        self.project_id = project_id
        self.trace_id = trace_id
        super().__init__(f"Trace not found: {trace_id} in project {project_id}")


class ProjectMissingError(Exception):
    def __init__(self, *, project_id: uuid.UUID | None = None, slug: str | None = None) -> None:
        self.project_id = project_id
        self.slug = slug
        detail = str(project_id) if project_id is not None else slug
        super().__init__(f"Project not found: {detail}")


@dataclass(frozen=True, slots=True)
class ListTracesQuery:
    project_id: uuid.UUID
    status: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    cursor: str | None = None
    limit: int = 50


@dataclass(frozen=True, slots=True)
class ListTracesResult:
    items: list[Trace]
    next_cursor: str | None
    span_counts: dict[uuid.UUID, int]


def encode_cursor(start_time: datetime, trace_pk: uuid.UUID) -> str:
    payload = {"t": start_time.isoformat(), "id": str(trace_pk)}
    return base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    raw = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8"))
    return datetime.fromisoformat(raw["t"]), uuid.UUID(raw["id"])


class IngestNormalizedTraces:
    def __init__(self, repository: TraceRepository) -> None:
        self._repository = repository

    async def execute(self, traces: list[Trace]) -> list[Trace]:
        saved: list[Trace] = []
        for trace in traces:
            saved.append(await self._repository.upsert(trace))
        return saved


class CreateTrace:
    def __init__(self, repository: TraceRepository) -> None:
        self._repository = repository

    async def execute(self, trace: Trace) -> Trace:
        return await self._repository.upsert(trace)


class ListTraces:
    def __init__(self, repository: TraceRepository) -> None:
        self._repository = repository

    async def execute(self, query: ListTracesQuery) -> ListTracesResult:
        cursor_start: datetime | None = None
        cursor_id: uuid.UUID | None = None
        if query.cursor:
            cursor_start, cursor_id = decode_cursor(query.cursor)

        limit = max(1, min(query.limit, 100))
        # fetch one extra to detect next page
        rows = await self._repository.list_by_project(
            query.project_id,
            status=query.status,
            start_time=query.start_time,
            end_time=query.end_time,
            cursor_start_time=cursor_start,
            cursor_id=cursor_id,
            limit=limit + 1,
        )
        next_cursor: str | None = None
        if len(rows) > limit:
            last = rows[limit - 1]
            next_cursor = encode_cursor(last.start_time, last.id)
            rows = rows[:limit]

        span_counts: dict[uuid.UUID, int] = {}
        cleaned: list[Trace] = []
        for trace in rows:
            meta = dict(trace.metadata)
            count = int(meta.pop("_span_count", 0))
            span_counts[trace.id] = count
            cleaned.append(
                Trace(
                    id=trace.id,
                    project_id=trace.project_id,
                    trace_id=trace.trace_id,
                    name=trace.name,
                    status=trace.status,
                    start_time=trace.start_time,
                    end_time=trace.end_time,
                    input=trace.input,
                    output=trace.output,
                    metadata=meta,
                    environment=trace.environment,
                    user_id=trace.user_id,
                    session_id=trace.session_id,
                    spans=trace.spans,
                )
            )

        return ListTracesResult(items=cleaned, next_cursor=next_cursor, span_counts=span_counts)


class GetTrace:
    def __init__(
        self,
        repository: TraceRepository,
        projects: ProjectRepository,
    ) -> None:
        self._repository = repository
        self._projects = projects

    async def execute(self, project_id: uuid.UUID, trace_id: str) -> Trace:
        project = await self._projects.get_by_id(project_id)
        if project is None:
            raise ProjectMissingError(project_id=project_id)
        trace = await self._repository.get_by_trace_id(project_id, trace_id)
        if trace is None:
            raise TraceNotFoundError(project_id, trace_id)
        return trace


class ResolveProject:
    def __init__(self, projects: ProjectRepository) -> None:
        self._projects = projects

    async def by_id(self, project_id: uuid.UUID) -> None:
        project = await self._projects.get_by_id(project_id)
        if project is None:
            raise ProjectMissingError(project_id=project_id)

    async def from_otlp_headers(
        self,
        *,
        project_id: str | None,
        project_slug: str | None,
    ) -> uuid.UUID:
        if bool(project_id) == bool(project_slug):
            # both missing or both set
            raise ValueError("Provide exactly one of X-Project-Id or X-Project-Slug")
        if project_id:
            try:
                pid = uuid.UUID(project_id)
            except ValueError as exc:
                raise ValueError("Invalid X-Project-Id") from exc
            project = await self._projects.get_by_id(pid)
            if project is None:
                raise ProjectMissingError(project_id=pid)
            return project.id
        assert project_slug is not None
        project = await self._projects.get_by_slug(project_slug)
        if project is None:
            raise ProjectMissingError(slug=project_slug)
        return project.id
