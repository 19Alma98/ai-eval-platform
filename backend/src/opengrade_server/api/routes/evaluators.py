from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from opengrade_server.api.deps import get_create_evaluator, get_list_evaluators
from opengrade_server.api.schemas import (
    CreateEvaluatorRequest,
    EvaluatorResponse,
    PreviewEvaluatorRequest,
    PreviewEvaluatorResponse,
)
from opengrade_server.application.evaluators import (
    CreateEvaluator,
    CreateEvaluatorCommand,
    ListEvaluators,
)
from opengrade_server.application.projects import ProjectNotFoundError
from opengrade_server.evaluation.judges.custom import CustomLlmJudge
from opengrade_server.evaluation.protocol import EvaluationSample
from opengrade_server.evaluation.registry import create_evaluator as build_evaluator

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
    try:
        evaluators = await use_case.execute(project_id)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return [EvaluatorResponse.model_validate(e) for e in evaluators]


@router.post(
    "/api/v1/projects/{project_id}/evaluators/preview",
    response_model=PreviewEvaluatorResponse,
)
async def preview_evaluator(
    project_id: uuid.UUID,
    body: PreviewEvaluatorRequest,
) -> PreviewEvaluatorResponse:
    """Run an evaluator config on one hand-written sample without saving anything.

    Meant for writing custom judges: check the verdict (and the prompt the judge
    receives) before using the judge on a test set or on live traffic.
    """
    kind = str(body.config.get("kind", "")).strip()
    try:
        evaluator = build_evaluator(kind, body.config)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown evaluator kind: {kind}"
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    sample = body.sample
    context = {"documents": sample.documents} if sample.documents is not None else None
    result = await evaluator.evaluate(
        EvaluationSample(
            input=sample.input,
            expected_output=sample.expected_output,
            actual_output=sample.output,
            context=context,
            metadata=dict(sample.metadata),
        )
    )
    return PreviewEvaluatorResponse(
        score=result.score,
        label=result.label,
        explanation=result.explanation,
        metadata=dict(result.metadata),
        system_prompt=(evaluator.system_prompt if isinstance(evaluator, CustomLlmJudge) else None),
    )
