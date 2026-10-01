from __future__ import annotations

import uuid
from dataclasses import dataclass

from aiobs.domain.project import Project
from aiobs.domain.repositories import ProjectRepository


class ProjectNotFoundError(Exception):
    def __init__(self, project_id: uuid.UUID) -> None:
        self.project_id = project_id
        super().__init__(f"Project not found: {project_id}")


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

    async def execute(self) -> list[Project]:
        return await self._repository.list_all()


class GetProject:
    def __init__(self, repository: ProjectRepository) -> None:
        self._repository = repository

    async def execute(self, project_id: uuid.UUID) -> Project:
        project = await self._repository.get_by_id(project_id)
        if project is None:
            raise ProjectNotFoundError(project_id)
        return project
