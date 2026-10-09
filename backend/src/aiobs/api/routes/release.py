from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from aiobs.api.deps import get_release_check
from aiobs.api.schemas import (
    ReleaseCheckItemResponse,
    ReleaseCheckRequest,
    ReleaseCheckResponse,
)
from aiobs.application.release_check import (
    ReleaseCheck,
    ReleaseCheckCommand,
)

router = APIRouter(prefix="/api/v1/projects", tags=["release"])


@router.post("/{project_id}/release-check", response_model=ReleaseCheckResponse)
async def release_check(
    project_id: uuid.UUID,
    body: ReleaseCheckRequest,
    use_case: ReleaseCheck = Depends(get_release_check),
) -> ReleaseCheckResponse:
    result = await use_case.execute(
        ReleaseCheckCommand(
            project_id=project_id,
            experiment_id=body.experiment_id,
            policy=body.policy.to_raw_dict(),
            baseline_experiment_id=body.baseline_experiment_id,
        )
    )
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
