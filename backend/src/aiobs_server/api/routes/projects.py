from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from aiobs_server.api.deps import (
    get_create_project,
    get_delete_project,
    get_get_project,
    get_list_projects,
)
from aiobs_server.api.schemas import CreateProjectRequest, ProjectResponse
from aiobs_server.application.projects import (
    CreateProject,
    CreateProjectCommand,
    DeleteProject,
    GetProject,
    ListProjects,
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
    return ProjectResponse.model_validate(project)


@router.get("", response_model=list[ProjectResponse])
async def list_projects(
    use_case: ListProjects = Depends(get_list_projects),
) -> list[ProjectResponse]:
    projects = await use_case.execute()
    return [ProjectResponse.model_validate(project) for project in projects]


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: uuid.UUID,
    use_case: GetProject = Depends(get_get_project),
) -> ProjectResponse:
    project = await use_case.execute(project_id)
    return ProjectResponse.model_validate(project)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: uuid.UUID,
    use_case: DeleteProject = Depends(get_delete_project),
) -> None:
    await use_case.execute(project_id)
