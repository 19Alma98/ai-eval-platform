from __future__ import annotations

import uuid
from dataclasses import dataclass

from opengrade_server.domain.project import Project
from opengrade_server.domain.repositories import ProjectRepository


class ProjectNotFoundError(Exception):
    def __init__(
        self,
        project_id: uuid.UUID | None = None,
        *,
        slug: str | None = None,
    ) -> None:
        if project_id is None and slug is None:
            raise TypeError("ProjectNotFoundError requires project_id or slug")
        self.project_id = project_id
        self.slug = slug
        label = str(project_id) if project_id is not None else f"slug={slug}"
        super().__init__(f"Project not found: {label}")


class ProjectSlugConflictError(Exception):
    def __init__(self, slug: str) -> None:
        self.slug = slug
        super().__init__(f"Project slug already exists: {slug}")


@dataclass(frozen=True, slots=True)
class CreateProjectCommand:
    name: str
    slug: str | None = None


class CreateProject:
    def __init__(self, repository: ProjectRepository) -> None:
        self._repository = repository

    async def execute(self, command: CreateProjectCommand) -> Project:
        project = Project.create(name=command.name, slug=command.slug)
        existing = await self._repository.get_by_slug(project.slug)
        if existing is not None:
            raise ProjectSlugConflictError(project.slug)
        return await self._repository.add(project)


class ListProjects:
    def __init__(self, repository: ProjectRepository) -> None:
        self._repository = repository

    async def execute(
        self,
        *,
        slug: str | None = None,
        name: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Project]:
        return await self._repository.list_all(slug=slug, name=name, limit=limit, offset=offset)


class GetProject:
    def __init__(self, repository: ProjectRepository) -> None:
        self._repository = repository

    async def execute(self, project_id: uuid.UUID) -> Project:
        project = await self._repository.get_by_id(project_id)
        if project is None:
            raise ProjectNotFoundError(project_id)
        return project


class GetProjectBySlug:
    def __init__(self, repository: ProjectRepository) -> None:
        self._repository = repository

    async def execute(self, slug: str) -> Project:
        project = await self._repository.get_by_slug(slug)
        if project is None:
            raise ProjectNotFoundError(slug=slug)
        return project


class DeleteProject:
    def __init__(self, repository: ProjectRepository) -> None:
        self._repository = repository

    async def execute(self, project_id: uuid.UUID) -> None:
        deleted = await self._repository.delete(project_id)
        if not deleted:
            raise ProjectNotFoundError(project_id)
