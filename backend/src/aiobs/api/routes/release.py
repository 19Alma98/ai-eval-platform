from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from aiobs.api.deps import get_release_check
from aiobs.api.schemas import (
    ReleaseCheckItemResponse,
    ReleaseCheckRequest,
    ReleaseCheckResponse,
)
from aiobs.application.compare import InvalidCompareSelectionError
from aiobs.application.experiments import ExperimentNotFoundError
from aiobs.application.projects import ProjectNotFoundError
from aiobs.application.release_check import (
    MissingBaselineError,
    ReleaseCheck,
    ReleaseCheckCommand,
)
from aiobs.regression.policy import InvalidPolicyError

router = APIRouter(prefix="/api/v1/projects", tags=["release"])


@router.post("/{project_id}/release-check", response_model=ReleaseCheckResponse)
async def release_check(
    project_id: uuid.UUID,
    body: ReleaseCheckRequest,
    use_case: ReleaseCheck = Depends(get_release_check),
) -> ReleaseCheckResponse:
    try:
        result = await use_case.execute(
            ReleaseCheckCommand(
                project_id=project_id,
                experiment_id=body.experiment_id,
                policy=body.policy,
                baseline_experiment_id=body.baseline_experiment_id,
            )
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ExperimentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except (
        InvalidPolicyError,
        MissingBaselineError,
        InvalidCompareSelectionError,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return ReleaseCheckResponse(
        status=result.status,
        experiment_id=result.experiment_id,
        baseline_experiment_id=result.baseline_experiment_id,
        checks=[
            ReleaseCheckItemResponse(
                metric=check.metric,
                actual=check.actual,
                threshold=check.threshold,
                status=check.status,
            )
            for check in result.checks.checks
        ],
    )
