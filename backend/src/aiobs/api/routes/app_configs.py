from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from aiobs.api.deps import (
    get_create_app_config,
    get_delete_app_config_alias,
    get_get_app_config,
    get_list_app_config_aliases,
    get_list_app_config_versions,
    get_list_app_configs,
    get_set_app_config_alias,
)
from aiobs.api.schemas import (
    AppConfigAliasResponse,
    AppConfigResponse,
    AppConfigSummaryResponse,
    CreateAppConfigRequest,
    SetAppConfigAliasRequest,
)
from aiobs.application.app_configs import (
    AppConfigAliasWithSummary,
    CreateAppConfig,
    CreateAppConfigCommand,
    DeleteAppConfigAlias,
    GetAppConfig,
    ListAppConfigAliases,
    ListAppConfigs,
    ListAppConfigVersions,
    SetAppConfigAlias,
    SetAppConfigAliasCommand,
)
from aiobs.domain.app_config import AppConfig

router = APIRouter(tags=["app-configs"])


def _app_config_response(config: AppConfig) -> AppConfigResponse:
    return AppConfigResponse.model_validate(
        {
            "id": config.id,
            "project_id": config.project_id,
            "name": config.name,
            "version": config.version,
            "description": config.description,
            "prompt": config.prompt,
            "model": config.model,
            "retrieval": config.retrieval,
            "content_hash": config.content_hash,
            "created_at": config.created_at,
        }
    )


def _alias_response(item: AppConfigAliasWithSummary) -> AppConfigAliasResponse:
    return AppConfigAliasResponse(
        name=item.alias.name,
        app_config_id=item.alias.app_config_id,
        updated_at=item.alias.updated_at,
        app_config=AppConfigSummaryResponse(
            id=item.config.id,
            name=item.config.name,
            version=item.config.version,
        ),
    )


@router.post(
    "/api/v1/projects/{project_id}/app-configs",
    response_model=AppConfigResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_app_config(
    project_id: uuid.UUID,
    body: CreateAppConfigRequest,
    use_case: CreateAppConfig = Depends(get_create_app_config),
) -> AppConfigResponse:
    try:
        config = await use_case.execute(
            CreateAppConfigCommand(
                project_id=project_id,
                name=body.name,
                description=body.description,
                prompt=body.prompt.model_dump(exclude_unset=True),
                model=body.model.model_dump(exclude_unset=True),
                retrieval=body.retrieval.model_dump(exclude_unset=True),
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _app_config_response(config)


@router.get(
    "/api/v1/projects/{project_id}/app-configs",
    response_model=list[AppConfigResponse],
)
async def list_app_configs(
    project_id: uuid.UUID,
    name: str | None = Query(default=None),
    latest: bool = Query(default=False),
    use_case: ListAppConfigs = Depends(get_list_app_configs),
) -> list[AppConfigResponse]:
    configs = await use_case.execute(project_id, name=name, latest_only=latest)
    return [_app_config_response(c) for c in configs]


@router.get("/api/v1/app-configs/{app_config_id}", response_model=AppConfigResponse)
async def get_app_config(
    app_config_id: uuid.UUID,
    use_case: GetAppConfig = Depends(get_get_app_config),
) -> AppConfigResponse:
    config = await use_case.execute(app_config_id)
    return _app_config_response(config)


@router.get(
    "/api/v1/projects/{project_id}/app-configs/by-name/{name}/versions",
    response_model=list[AppConfigResponse],
)
async def list_app_config_versions(
    project_id: uuid.UUID,
    name: str,
    use_case: ListAppConfigVersions = Depends(get_list_app_config_versions),
) -> list[AppConfigResponse]:
    configs = await use_case.execute(project_id, name)
    return [_app_config_response(c) for c in configs]


@router.put(
    "/api/v1/projects/{project_id}/app-config-aliases/{alias}",
    response_model=AppConfigAliasResponse,
)
async def set_app_config_alias(
    project_id: uuid.UUID,
    alias: str,
    body: SetAppConfigAliasRequest,
    set_alias: SetAppConfigAlias = Depends(get_set_app_config_alias),
    get_config: GetAppConfig = Depends(get_get_app_config),
) -> AppConfigAliasResponse:
    try:
        alias_row = await set_alias.execute(
            SetAppConfigAliasCommand(
                project_id=project_id,
                alias=alias,
                app_config_id=body.app_config_id,
            )
        )
        config = await get_config.execute(alias_row.app_config_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _alias_response(AppConfigAliasWithSummary(alias=alias_row, config=config))


@router.get(
    "/api/v1/projects/{project_id}/app-config-aliases",
    response_model=list[AppConfigAliasResponse],
)
async def list_app_config_aliases(
    project_id: uuid.UUID,
    use_case: ListAppConfigAliases = Depends(get_list_app_config_aliases),
) -> list[AppConfigAliasResponse]:
    items = await use_case.execute(project_id)
    return [_alias_response(i) for i in items]


@router.delete(
    "/api/v1/projects/{project_id}/app-config-aliases/{alias}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_app_config_alias(
    project_id: uuid.UUID,
    alias: str,
    use_case: DeleteAppConfigAlias = Depends(get_delete_app_config_alias),
) -> Response:
    try:
        await use_case.execute(project_id, alias)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
