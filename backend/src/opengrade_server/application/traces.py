from __future__ import annotations

import base64
import binascii
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from opengrade_server.domain.repositories import (
    LiveInteractionRepository,
    ProjectRepository,
    TraceRepository,
    TraceScoreRepository,
)
from opengrade_server.domain.trace import Trace
from opengrade_server.domain.trace_score import TraceScore, normalize_trace_id

# Same prefix live_binding uses for trace-derived live interactions.
LIVE_EXTERNAL_ID_PREFIX = "trace:"


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


class IngestNormalizedTraces:
    def __init__(self, repository: TraceRepository) -> None:
        self._repository = repository

    async def execute(self, traces: list[Trace]) -> list[Trace]:
        saved: list[Trace] = []
        for trace in traces:
            saved.append(await self._repository.upsert(trace))
        return saved


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
        try:
            trace_id = normalize_trace_id(trace_id)
        except ValueError as exc:
            raise TraceNotFoundError(project_id, trace_id) from exc
        trace = await self._repository.get_by_trace_id(project_id, trace_id)
        if trace is None:
            raise TraceNotFoundError(project_id, trace_id)
        return trace


class InvalidTraceCursorError(ValueError):
    pass


def encode_trace_cursor(trace: Trace) -> str:
    raw = f"{trace.start_time.isoformat()}|{trace.id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_trace_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        start, _, pk = base64.urlsafe_b64decode(padded).decode().partition("|")
        return datetime.fromisoformat(start), uuid.UUID(pk)
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise InvalidTraceCursorError("invalid cursor") from exc


class ResolveTraceLiveLinks:
    """Live interaction id for each trace that produced one (production traffic)."""

    def __init__(self, live: LiveInteractionRepository) -> None:
        self._live = live

    async def execute(self, project_id: uuid.UUID, trace_ids: list[str]) -> dict[str, uuid.UUID]:
        by_external = await self._live.ids_by_external_ids(
            project_id, [f"{LIVE_EXTERNAL_ID_PREFIX}{tid}" for tid in trace_ids]
        )
        return {ext.removeprefix(LIVE_EXTERNAL_ID_PREFIX): pk for ext, pk in by_external.items()}


@dataclass(frozen=True, slots=True)
class TraceListPage:
    traces: list[Trace]
    next_cursor: str | None
    scores: dict[str, list[TraceScore]] = field(default_factory=dict)
    live_interaction_ids: dict[str, uuid.UUID] = field(default_factory=dict)


class ListTraces:
    def __init__(
        self,
        repository: TraceRepository,
        projects: ProjectRepository,
        trace_scores: TraceScoreRepository,
        live_links: ResolveTraceLiveLinks,
    ) -> None:
        self._repository = repository
        self._projects = projects
        self._trace_scores = trace_scores
        self._live_links = live_links

    async def execute(
        self,
        project_id: uuid.UUID,
        *,
        status: str | None = None,
        search: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        cursor: str | None = None,
        limit: int = 50,
        environment: str | None = None,
        version: str | None = None,
    ) -> TraceListPage:
        if await self._projects.get_by_id(project_id) is None:
            raise ProjectMissingError(project_id=project_id)
        cursor_start, cursor_id = decode_trace_cursor(cursor) if cursor else (None, None)
        # One extra row tells whether another page exists.
        rows = await self._repository.list_by_project(
            project_id,
            status=status,
            search=search,
            start_time=since,
            end_time=until,
            cursor_start_time=cursor_start,
            cursor_id=cursor_id,
            limit=limit + 1,
            environment=environment,
            version=version,
        )
        page = rows[:limit]
        next_cursor = encode_trace_cursor(page[-1]) if len(rows) > limit and page else None
        trace_ids = [t.trace_id for t in page]
        return TraceListPage(
            traces=page,
            next_cursor=next_cursor,
            scores=await self._trace_scores.list_by_trace_ids(project_id, trace_ids),
            live_interaction_ids=await self._live_links.execute(project_id, trace_ids),
        )


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
