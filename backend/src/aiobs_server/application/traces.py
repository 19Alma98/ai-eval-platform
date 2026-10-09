from __future__ import annotations

import uuid

from aiobs_server.domain.repositories import ProjectRepository, TraceRepository
from aiobs_server.domain.trace import Trace


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
