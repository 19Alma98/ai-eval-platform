from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from opengrade_server.api.deps import (
    get_delete_experiment_alias,
    get_get_experiment_alias,
    get_list_experiment_alias_history,
    get_list_experiment_aliases,
    get_set_experiment_alias,
)
from opengrade_server.api.schemas import (
    ExperimentAliasEventResponse,
    ExperimentAliasResponse,
    ExperimentAliasTargetResponse,
    SetExperimentAliasRequest,
)
from opengrade_server.application.experiment_aliases import (
    DeleteExperimentAlias,
    GetExperimentAlias,
    ListExperimentAliases,
    ListExperimentAliasHistory,
    SetExperimentAlias,
    SetExperimentAliasCommand,
)
from opengrade_server.domain.experiment import Experiment
from opengrade_server.domain.experiment_alias import ExperimentAlias, ExperimentAliasEvent

router = APIRouter(tags=["experiment-aliases"])


def _target_response(experiment: Experiment) -> ExperimentAliasTargetResponse:
    return ExperimentAliasTargetResponse(
        id=experiment.id,
        name=experiment.name,
        version=experiment.version,
        dataset_id=experiment.dataset_id,
        metrics_set_id=experiment.metrics_set_id,
        status=experiment.status,
        created_at=experiment.created_at,
    )


def _alias_response(
    alias: ExperimentAlias,
    experiment: Experiment,
    *,
    previous_experiment_id: uuid.UUID | None = None,
    changed: bool | None = None,
) -> ExperimentAliasResponse:
    return ExperimentAliasResponse(
        name=alias.name,
        experiment_id=alias.experiment_id,
        updated_at=alias.updated_at,
        experiment=_target_response(experiment),
        previous_experiment_id=previous_experiment_id,
        changed=changed,
    )


def _event_response(event: ExperimentAliasEvent) -> ExperimentAliasEventResponse:
    return ExperimentAliasEventResponse(
        id=event.id,
        name=event.name,
        experiment_id=event.experiment_id,
        previous_experiment_id=event.previous_experiment_id,
        note=event.note,
        created_at=event.created_at,
    )


@router.put(
    "/api/v1/projects/{project_id}/experiment-aliases/{alias}",
    response_model=ExperimentAliasResponse,
)
async def set_experiment_alias(
    project_id: uuid.UUID,
    alias: str,
    body: SetExperimentAliasRequest,
    use_case: SetExperimentAlias = Depends(get_set_experiment_alias),
) -> ExperimentAliasResponse:
    try:
        result = await use_case.execute(
            SetExperimentAliasCommand(
                project_id=project_id,
                alias=alias,
                experiment_id=body.experiment_id,
                note=body.note,
                force=body.force,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _alias_response(
        result.alias,
        result.experiment,
        previous_experiment_id=result.previous_experiment_id,
        changed=result.changed,
    )


@router.get(
    "/api/v1/projects/{project_id}/experiment-aliases",
    response_model=list[ExperimentAliasResponse],
)
async def list_experiment_aliases(
    project_id: uuid.UUID,
    use_case: ListExperimentAliases = Depends(get_list_experiment_aliases),
) -> list[ExperimentAliasResponse]:
    items = await use_case.execute(project_id)
    return [_alias_response(item.alias, item.experiment) for item in items]


@router.get(
    "/api/v1/projects/{project_id}/experiment-aliases/{alias}",
    response_model=ExperimentAliasResponse,
)
async def get_experiment_alias(
    project_id: uuid.UUID,
    alias: str,
    use_case: GetExperimentAlias = Depends(get_get_experiment_alias),
) -> ExperimentAliasResponse:
    item = await use_case.execute(project_id, alias)
    return _alias_response(item.alias, item.experiment)


@router.get(
    "/api/v1/projects/{project_id}/experiment-aliases/{alias}/history",
    response_model=list[ExperimentAliasEventResponse],
)
async def list_experiment_alias_history(
    project_id: uuid.UUID,
    alias: str,
    limit: int = Query(default=50, ge=1, le=500),
    use_case: ListExperimentAliasHistory = Depends(get_list_experiment_alias_history),
) -> list[ExperimentAliasEventResponse]:
    events = await use_case.execute(project_id, alias, limit=limit)
    return [_event_response(event) for event in events]


@router.delete(
    "/api/v1/projects/{project_id}/experiment-aliases/{alias}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_experiment_alias(
    project_id: uuid.UUID,
    alias: str,
    use_case: DeleteExperimentAlias = Depends(get_delete_experiment_alias),
) -> Response:
    await use_case.execute(project_id, alias)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
