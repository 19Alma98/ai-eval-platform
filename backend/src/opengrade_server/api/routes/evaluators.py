from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from aiobs_server.api.deps import get_create_evaluator, get_list_evaluators
from aiobs_server.api.schemas import CreateEvaluatorRequest, EvaluatorResponse
from aiobs_server.application.evaluators import (
    CreateEvaluator,
    CreateEvaluatorCommand,
    ListEvaluators,
)

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
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return EvaluatorResponse.model_validate(evaluator)


@router.get(
    "/api/v1/projects/{project_id}/evaluators",
    response_model=list[EvaluatorResponse],
)
async def list_evaluators(
    project_id: uuid.UUID,
    use_case: ListEvaluators = Depends(get_list_evaluators),
) -> list[EvaluatorResponse]:
    evaluators = await use_case.execute(project_id)
    return [EvaluatorResponse.model_validate(e) for e in evaluators]
