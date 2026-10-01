from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError

from aiobs.api.deps import get_create_evaluator, get_list_evaluators
from aiobs.api.schemas import CreateEvaluatorRequest, EvaluatorResponse
from aiobs.application.evaluators import (
    CreateEvaluator,
    CreateEvaluatorCommand,
    EvaluatorConflictError,
    ListEvaluators,
    UnknownEvaluatorKindError,
)
from aiobs.application.projects import ProjectNotFoundError

router = APIRouter(tags=["evaluators"])


@router.post(
    "/api/v1/projects/{project_id}/evaluators",
    response_model=EvaluatorResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_evaluator(
    project_id: uuid.UUID,
    body: CreateEvaluatorRequest,
    use_case: CreateEvaluator = Depends(get_create_evaluator),
) -> EvaluatorResponse:
    try:
        evaluator = await use_case.execute(
            CreateEvaluatorCommand(
                project_id=project_id,
                name=body.name,
                type=body.type,
                config=body.config,
                version=body.version,
            )
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except UnknownEvaluatorKindError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except (EvaluatorConflictError, IntegrityError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return EvaluatorResponse(
        id=evaluator.id,
        project_id=evaluator.project_id,
        name=evaluator.name,
        type=evaluator.type,
        config=evaluator.config,
        version=evaluator.version,
    )


@router.get(
    "/api/v1/projects/{project_id}/evaluators",
    response_model=list[EvaluatorResponse],
)
async def list_evaluators(
    project_id: uuid.UUID,
    use_case: ListEvaluators = Depends(get_list_evaluators),
) -> list[EvaluatorResponse]:
    evaluators = await use_case.execute(project_id)
    return [
        EvaluatorResponse(
            id=e.id,
            project_id=e.project_id,
            name=e.name,
            type=e.type,
            config=e.config,
            version=e.version,
        )
        for e in evaluators
    ]
