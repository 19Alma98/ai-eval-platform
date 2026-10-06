from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from aiobs.api.deps import get_app_config_repository, get_project_repository
from aiobs.domain.app_config import AppConfig, AppConfigAlias
from aiobs.main import create_app


class InMemoryProjectRepository:
    def __init__(self) -> None:
        self._projects: dict[uuid.UUID, Any] = {}

    async def add(self, project: Any) -> Any:
        self._projects[project.id] = project
        return project

    async def get_by_id(self, project_id: uuid.UUID) -> Any | None:
        return self._projects.get(project_id)

    async def get_by_slug(self, slug: str) -> Any | None:
        for project in self._projects.values():
            if project.slug == slug:
                return project
        return None

    async def list_all(self) -> list[Any]:
        return list(self._projects.values())


class InMemoryAppConfigRepository:
    def __init__(self) -> None:
        self._configs: dict[uuid.UUID, AppConfig] = {}
        self._aliases: dict[tuple[uuid.UUID, str], AppConfigAlias] = {}

    async def add(self, config: AppConfig) -> AppConfig:
        for existing in self._configs.values():
            if (
                existing.project_id == config.project_id
                and existing.name == config.name
                and existing.version == config.version
            ):
                raise Exception("unique constraint")
        self._configs[config.id] = config
        return config

    async def get_by_id(self, app_config_id: uuid.UUID) -> AppConfig | None:
        return self._configs.get(app_config_id)

    async def list_by_project(
        self,
        project_id: uuid.UUID,
        *,
        name: str | None = None,
        latest_only: bool = False,
    ) -> list[AppConfig]:
        items = [c for c in self._configs.values() if c.project_id == project_id]
        if name is not None:
            items = [c for c in items if c.name == name]
        if latest_only:
            latest: dict[str, AppConfig] = {}
            for cfg in items:
                prev = latest.get(cfg.name)
                if prev is None or cfg.version > prev.version:
                    latest[cfg.name] = cfg
            return sorted(latest.values(), key=lambda c: c.name)
        return sorted(items, key=lambda c: c.created_at, reverse=True)

    async def list_versions(self, project_id: uuid.UUID, name: str) -> list[AppConfig]:
        items = [c for c in self._configs.values() if c.project_id == project_id and c.name == name]
        return sorted(items, key=lambda c: c.version)

    async def next_version(self, project_id: uuid.UUID, name: str) -> int:
        versions = [
            c.version
            for c in self._configs.values()
            if c.project_id == project_id and c.name == name
        ]
        return max(versions, default=0) + 1

    async def set_alias(self, alias: AppConfigAlias) -> AppConfigAlias:
        self._aliases[(alias.project_id, alias.name)] = alias
        return alias

    async def get_alias(self, project_id: uuid.UUID, name: str) -> AppConfigAlias | None:
        return self._aliases.get((project_id, name))

    async def list_aliases(self, project_id: uuid.UUID) -> list[AppConfigAlias]:
        return sorted(
            (a for (pid, _), a in self._aliases.items() if pid == project_id),
            key=lambda a: a.name,
        )

    async def delete_alias(self, project_id: uuid.UUID, name: str) -> bool:
        return self._aliases.pop((project_id, name), None) is not None


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    projects = InMemoryProjectRepository()
    app_configs = InMemoryAppConfigRepository()

    app = create_app()
    app.dependency_overrides[get_project_repository] = lambda: projects
    app.dependency_overrides[get_app_config_repository] = lambda: app_configs

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


def _sample_config_body() -> dict[str, Any]:
    return {
        "name": "rag-faq",
        "description": "demo",
        "prompt": {"system": "You are helpful."},
        "model": {"model_id": "gpt-demo"},
        "retrieval": {"top_k": 5},
    }


@pytest.mark.asyncio
async def test_create_app_config_versions_and_aliases(client: AsyncClient) -> None:
    project = await client.post("/api/v1/projects", json={"name": "AppConfig Demo"})
    assert project.status_code == 201
    project_id = project.json()["id"]

    v1 = await client.post(
        f"/api/v1/projects/{project_id}/app-configs",
        json=_sample_config_body(),
    )
    assert v1.status_code == 201, v1.text
    v1_body = v1.json()
    assert v1_body["version"] == 1
    assert v1_body["name"] == "rag-faq"
    v1_id = v1_body["id"]

    v2 = await client.post(
        f"/api/v1/projects/{project_id}/app-configs",
        json={
            **_sample_config_body(),
            "prompt": {"system": "You are very helpful."},
        },
    )
    assert v2.status_code == 201, v2.text
    v2_body = v2.json()
    assert v2_body["version"] == 2
    v2_id = v2_body["id"]
    assert v2_id != v1_id

    listed = await client.get(f"/api/v1/projects/{project_id}/app-configs")
    assert listed.status_code == 200, listed.text
    all_configs = listed.json()
    assert len(all_configs) == 2
    assert {c["id"] for c in all_configs} == {v1_id, v2_id}

    by_name = await client.get(
        f"/api/v1/projects/{project_id}/app-configs",
        params={"name": "rag-faq"},
    )
    assert by_name.status_code == 200, by_name.text
    assert len(by_name.json()) == 2

    latest = await client.get(
        f"/api/v1/projects/{project_id}/app-configs",
        params={"latest": "true"},
    )
    assert latest.status_code == 200, latest.text
    latest_list = latest.json()
    assert len(latest_list) == 1
    assert latest_list[0]["version"] == 2
    assert latest_list[0]["id"] == v2_id

    versions = await client.get(
        f"/api/v1/projects/{project_id}/app-configs/by-name/rag-faq/versions",
    )
    assert versions.status_code == 200, versions.text
    version_list = versions.json()
    assert [c["version"] for c in version_list] == [1, 2]
    assert version_list[0]["id"] == v1_id
    assert version_list[1]["id"] == v2_id

    put_alias = await client.put(
        f"/api/v1/projects/{project_id}/app-config-aliases/baseline",
        json={"app_config_id": v1_id},
    )
    assert put_alias.status_code == 200, put_alias.text

    aliases = await client.get(f"/api/v1/projects/{project_id}/app-config-aliases")
    assert aliases.status_code == 200, aliases.text
    alias_list = aliases.json()
    assert len(alias_list) == 1
    assert alias_list[0]["name"] == "baseline"
    assert alias_list[0]["app_config"]["id"] == v1_id
    assert alias_list[0]["app_config"]["name"] == "rag-faq"
    assert alias_list[0]["app_config"]["version"] == 1

    move = await client.put(
        f"/api/v1/projects/{project_id}/app-config-aliases/baseline",
        json={"app_config_id": v2_id},
    )
    assert move.status_code == 200, move.text

    aliases_after = await client.get(f"/api/v1/projects/{project_id}/app-config-aliases")
    assert aliases_after.json()[0]["app_config"]["version"] == 2

    unknown = await client.get(f"/api/v1/app-configs/{uuid.uuid4()}")
    assert unknown.status_code == 404

    other = await client.post("/api/v1/projects", json={"name": "Other"})
    other_id = other.json()["id"]
    cross = await client.put(
        f"/api/v1/projects/{other_id}/app-config-aliases/baseline",
        json={"app_config_id": v2_id},
    )
    assert cross.status_code == 404

    deleted = await client.delete(
        f"/api/v1/projects/{project_id}/app-config-aliases/baseline",
    )
    assert deleted.status_code == 204
    empty = await client.get(f"/api/v1/projects/{project_id}/app-config-aliases")
    assert empty.json() == []
