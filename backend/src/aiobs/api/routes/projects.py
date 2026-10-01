from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from aiobs.api.deps import get_create_project, get_get_project, get_list_projects
from aiobs.api.schemas import CreateProjectRequest, ProjectResponse
from aiobs.application.projects import (
    CreateProject,
    CreateProjectCommand,
    GetProject,
    ListProjects,
    ProjectNotFoundError,
    ProjectSlugConflictError,
)

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: CreateProjectRequest,
    use_case: CreateProject = Depends(get_create_project),
) -> ProjectResponse:
    try:
        project = await use_case.execute(CreateProjectCommand(name=body.name, slug=body.slug))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ProjectSlugConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    return ProjectResponse(
        id=project.id,
        name=project.name,
        slug=project.slug,
        created_at=project.created_at,
    )


@router.get("", response_model=list[ProjectResponse])
async def list_projects(
    use_case: ListProjects = Depends(get_list_projects),
) -> list[ProjectResponse]:
    projects = await use_case.execute()
    return [
        ProjectResponse(
            id=project.id,
            name=project.name,
            slug=project.slug,
            created_at=project.created_at,
        )
        for project in projects
    ]


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: uuid.UUID,
    use_case: GetProject = Depends(get_get_project),
) -> ProjectResponse:
    try:
        project = await use_case.execute(project_id)
    except ProjectNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    return ProjectResponse(
        id=project.id,
        name=project.name,
        slug=project.slug,
        created_at=project.created_at,
    )
