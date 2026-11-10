from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Iterator
from typing import Any

import httpx2
import pytest
from tests.support.instance import activated, make_og
from tests.support.reset import reset_sdk

import opengrade
from opengrade import Opengrade, Settings, current
from opengrade._config import otlp_endpoint, resolve_config


@pytest.fixture(autouse=True)
def reset_state(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name in (
        "OPENGRADE_TRACKING_URI",
        "OPENGRADE_OTLP_ENDPOINT",
        "OPENGRADE_PROJECT_ID",
        "OPENGRADE_PROJECT_SLUG",
    ):
        monkeypatch.delenv(name, raising=False)
    reset_sdk(otel=True)
    yield
    reset_sdk(otel=True)


def _project(pid: str, name: str, slug: str) -> dict[str, Any]:
    return {"id": pid, "name": name, "slug": slug, "created_at": "2026-01-01T00:00:00+00:00"}


class FakeServer:
    def __init__(self, projects: list[dict[str, Any]] | None = None) -> None:
        self.projects = list(projects or [])
        self.created: list[dict[str, Any]] = []
        self.conflict_once_with: dict[str, Any] | None = None

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        path = request.url.path.rstrip("/")
        if request.method == "GET" and path == "/api/v1/projects":
            projects = self.projects
            slug = request.url.params.get("slug")
            name = request.url.params.get("name")
            if slug is not None:
                projects = [p for p in projects if p["slug"] == slug]
            if name is not None:
                projects = [p for p in projects if p["name"] == name]
            return httpx2.Response(200, json=projects)
        if request.method == "POST" and path == "/api/v1/projects":
            if self.conflict_once_with is not None:
                self.projects.append(self.conflict_once_with)
                self.conflict_once_with = None
                return httpx2.Response(409, json={"detail": "slug exists"})
            body = json.loads(request.content)
            self.created.append(body)
            created = _project(f"proj-{len(self.projects) + 1}", body["name"], body["slug"])
            self.projects.append(created)
            return httpx2.Response(201, json=created)
        return httpx2.Response(404, json={"detail": "not found"})

    def install(self, og: Opengrade) -> None:
        transport = httpx2.MockTransport(self.handler)
        og._runtime.client = opengrade.Client("http://test", transport=transport)
        async_client = opengrade.AsyncClient("http://test", transport=transport)
        og._runtime.async_client_no_loop = async_client
        try:
            loop = asyncio.get_running_loop()
            og._runtime.async_clients[loop] = async_client
        except RuntimeError:
            pass


def test_tracking_uri_default_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    og = make_og()
    assert og.client.base_url == "http://localhost:8000"
    monkeypatch.setenv("OPENGRADE_TRACKING_URI", "http://env:2/")
    og = Opengrade(Settings.from_env())
    assert og.client.base_url == "http://env:2"
    og = make_og(tracking_uri="http://explicit:3/")
    assert og.client.base_url == "http://explicit:3"


def test_tracking_uri_drives_client_and_otlp() -> None:
    og = make_og(tracking_uri="http://platform:9000")
    assert og.client.base_url == "http://platform:9000"
    cfg = resolve_config(project_slug="demo", runtime=og._runtime)
    assert cfg.endpoint == "http://platform:9000/v1/traces"


def test_otlp_endpoint_env_still_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    og = make_og(tracking_uri="http://platform:9000")
    monkeypatch.setenv("OPENGRADE_OTLP_ENDPOINT", "http://collector:4318/v1/traces")
    assert otlp_endpoint(runtime=og._runtime) == "http://collector:4318/v1/traces"


def test_client_is_shared_until_settings_change() -> None:
    og = make_og(tracking_uri="http://first:1")
    first = og.client
    assert og.client is first
    og = make_og(tracking_uri="http://other:1")
    second = og.client
    assert second is not first
    assert second.base_url == "http://other:1"


def test_async_client_per_event_loop() -> None:
    og = make_og(tracking_uri="http://test", project_id="p1")
    clients: list[object] = []

    async def grab() -> None:
        with activated(og):
            clients.append(og.async_client())

    asyncio.run(grab())
    asyncio.run(grab())
    assert len(clients) == 2
    assert clients[0] is not clients[1]


def test_set_project_platform_down_returns_none(caplog: pytest.LogCaptureFixture) -> None:
    og = make_og(tracking_uri="http://127.0.0.1:9")
    with activated(og):
        with caplog.at_level(logging.WARNING, logger="opengrade"):
            assert og.set_project("demo") is None
    assert any("set_project" in r.message for r in caplog.records)


def test_after_fork_hook_resets_runtime_clients() -> None:
    if not hasattr(os, "register_at_fork"):
        pytest.skip("fork hooks not available")
    og = make_og(tracking_uri="http://parent", project_id="p1")
    parent = og.client
    parent_async = og.async_client()
    og._runtime.after_fork_in_child()
    child = og.client
    child_async = og.async_client()
    assert child is not parent
    assert child_async is not parent_async


def test_set_project_creates_when_missing() -> None:
    og = make_og(project_id="p1")
    server = FakeServer()
    with activated(og):
        server.install(og)
        project = og.set_project("HR Assistant")
    assert server.created == [{"name": "HR Assistant", "slug": "hr-assistant"}]
    assert project is not None and project.slug == "hr-assistant"
    assert og.get_project() == project


def test_set_project_reuses_existing_by_slug() -> None:
    og = make_og(project_id="p1")
    server = FakeServer([_project("p-1", "Whatever", "hr-assistant")])
    with activated(og):
        server.install(og)
        project = og.set_project("hr-assistant")
    assert project is not None and project.id == "p-1"
    assert server.created == []


def test_set_project_reuses_existing_by_name() -> None:
    og = make_og(project_id="p1")
    server = FakeServer([_project("p-1", "HR Assistant", "custom-slug")])
    with activated(og):
        server.install(og)
        assert og.set_project("HR Assistant").id == "p-1"
    assert server.created == []


def test_set_project_handles_concurrent_create() -> None:
    og = make_og(project_id="p1")
    server = FakeServer()
    server.conflict_once_with = _project("p-race", "hr-assistant", "hr-assistant")
    with activated(og):
        server.install(og)
        assert og.set_project("hr-assistant").id == "p-race"


def test_set_project_rejects_empty() -> None:
    og = make_og(project_id="p1")
    with activated(og):
        with pytest.raises(ValueError, match="must not be empty"):
            og.set_project("  ")


def test_aset_project_creates_when_missing() -> None:
    og = make_og(project_id="p1")
    server = FakeServer()

    async def main() -> None:
        with activated(og):
            server.install(og)
            project = await og.aset_project("HR Assistant")
        assert server.created == [{"name": "HR Assistant", "slug": "hr-assistant"}]
        assert project is not None
        assert project.slug == "hr-assistant"
        assert og.get_project() == project

    asyncio.run(main())


def test_aset_project_reuses_existing_by_slug() -> None:
    og = make_og(project_id="p1")
    server = FakeServer([_project("p-1", "Whatever", "hr-assistant")])

    async def main() -> None:
        with activated(og):
            server.install(og)
            project = await og.aset_project("hr-assistant")
        assert project is not None and project.id == "p-1"
        assert server.created == []

    asyncio.run(main())


def test_init_uses_active_project(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENGRADE_PROJECT_SLUG", "from-env")
    og = Opengrade(Settings.from_env(project_slug="from-env"))
    server = FakeServer([_project("p-1", "hr", "hr")])
    with activated(og):
        server.install(og)
        og.set_project("hr")
        cfg = resolve_config(runtime=og._runtime)
        assert cfg.project_id == "p-1"
        assert cfg.project_slug is None
        og.init_tracing(instrument=False)
    assert og.tracing_enabled is True


def test_resources_default_to_active_project() -> None:
    seen: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request.url.path)
        if request.url.path == "/api/v1/projects":
            return httpx2.Response(200, json=[_project("p-1", "hr", "hr")])
        return httpx2.Response(200, json=[])

    og = make_og(project_id="p1")
    og._runtime.client = opengrade.Client("http://test", transport=httpx2.MockTransport(handler))
    with activated(og):
        og.set_project("hr")
        client = current().client
        client.datasets.list()
        client.experiments.list()
        client.datasets.list("explicit")
    assert seen[-3:] == [
        "/api/v1/projects/p-1/datasets",
        "/api/v1/projects/p-1/experiments",
        "/api/v1/projects/explicit/datasets",
    ]


def test_bare_client_does_not_use_env_project_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENGRADE_PROJECT_ID", "env-pid")

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=[])

    client = opengrade.Client("http://test", transport=httpx2.MockTransport(handler))
    with pytest.raises(ValueError, match="project_id is required"):
        client.experiments.list()


def test_settings_binds_env_project_id_on_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENGRADE_PROJECT_ID", "env-pid")
    seen: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request.url.path)
        return httpx2.Response(200, json=[])

    og = Opengrade(Settings.from_env())
    og._runtime.client = opengrade.Client(
        "http://test", transport=httpx2.MockTransport(handler), project_id="env-pid"
    )
    with activated(og):
        og.client.experiments.list()
    assert seen == ["/api/v1/projects/env-pid/experiments"]


def test_resources_without_project_raise() -> None:
    with pytest.raises(ValueError, match="project_id is required"):
        opengrade.Client("http://test").datasets.list()
