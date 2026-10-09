from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from aiobs_server.application.projects import ProjectNotFoundError
from aiobs_server.domain.app_config import AppConfig, AppConfigAlias
from aiobs_server.domain.repositories import AppConfigRepository, ProjectRepository


class AppConfigNotFoundError(Exception):
    def __init__(self, app_config_id: uuid.UUID) -> None:
        self.app_config_id = app_config_id
        super().__init__(f"App config not found: {app_config_id}")


class AppConfigAliasNotFoundError(Exception):
    def __init__(self, project_id: uuid.UUID, alias: str) -> None:
        self.project_id = project_id
        self.alias = alias
        super().__init__(f"App config alias not found: {alias} in project {project_id}")


@dataclass(frozen=True, slots=True)
class CreateAppConfigCommand:
    project_id: uuid.UUID
    name: str
    description: str | None = None
    prompt: dict[str, Any] | None = None
    model: dict[str, Any] | None = None
    retrieval: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class SetAppConfigAliasCommand:
    project_id: uuid.UUID
    alias: str
    app_config_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class AppConfigAliasWithSummary:
    alias: AppConfigAlias
    config: AppConfig


class CreateAppConfig:
    def __init__(
        self,
        app_configs: AppConfigRepository,
        projects: ProjectRepository,
    ) -> None:
        self._app_configs = app_configs
        self._projects = projects

    async def execute(self, command: CreateAppConfigCommand) -> AppConfig:
        project = await self._projects.get_by_id(command.project_id)
        if project is None:
            raise ProjectNotFoundError(command.project_id)
        version = await self._app_configs.next_version(command.project_id, command.name.strip())
        config = AppConfig.create(
            command.project_id,
            command.name,
            version=version,
            description=command.description,
            prompt=command.prompt,
            model=command.model,
            retrieval=command.retrieval,
        )
        return await self._app_configs.add(config)


class ListAppConfigs:
    def __init__(self, app_configs: AppConfigRepository) -> None:
        self._app_configs = app_configs

    async def execute(
        self,
        project_id: uuid.UUID,
        *,
        name: str | None = None,
        latest_only: bool = False,
    ) -> list[AppConfig]:
        return await self._app_configs.list_by_project(
            project_id,
            name=name,
            latest_only=latest_only,
        )


class GetAppConfig:
    def __init__(self, app_configs: AppConfigRepository) -> None:
        self._app_configs = app_configs

    async def execute(self, app_config_id: uuid.UUID) -> AppConfig:
        config = await self._app_configs.get_by_id(app_config_id)
        if config is None:
            raise AppConfigNotFoundError(app_config_id)
        return config


class ListAppConfigVersions:
    def __init__(self, app_configs: AppConfigRepository) -> None:
        self._app_configs = app_configs

    async def execute(self, project_id: uuid.UUID, name: str) -> list[AppConfig]:
        return await self._app_configs.list_versions(project_id, name)


class SetAppConfigAlias:
    def __init__(self, app_configs: AppConfigRepository) -> None:
        self._app_configs = app_configs

    async def execute(self, command: SetAppConfigAliasCommand) -> AppConfigAlias:
        config = await self._app_configs.get_by_id(command.app_config_id)
        if config is None or config.project_id != command.project_id:
            raise AppConfigNotFoundError(command.app_config_id)
        alias = AppConfigAlias.create(
            command.project_id,
            command.alias,
            command.app_config_id,
        )
        return await self._app_configs.set_alias(alias)


class ListAppConfigAliases:
    def __init__(self, app_configs: AppConfigRepository) -> None:
        self._app_configs = app_configs

    async def execute(self, project_id: uuid.UUID) -> list[AppConfigAliasWithSummary]:
        aliases = await self._app_configs.list_aliases(project_id)
        result: list[AppConfigAliasWithSummary] = []
        for alias in aliases:
            config = await self._app_configs.get_by_id(alias.app_config_id)
            if config is None:
                raise AppConfigNotFoundError(alias.app_config_id)
            result.append(AppConfigAliasWithSummary(alias=alias, config=config))
        return result


class DeleteAppConfigAlias:
    def __init__(self, app_configs: AppConfigRepository) -> None:
        self._app_configs = app_configs

    async def execute(self, project_id: uuid.UUID, alias: str) -> None:
        deleted = await self._app_configs.delete_alias(project_id, alias.strip())
        if not deleted:
            raise AppConfigAliasNotFoundError(project_id, alias)
