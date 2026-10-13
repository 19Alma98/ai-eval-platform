from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any

import httpx2
import pytest

import aiobs
from aiobs import _context, _otel
from aiobs._config import resolve_config


def _project(pid: str, name: str, slug: str) -> dict[str, Any]:
    return {"id": pid, "name": name, "slug": slug, "created_at": "2026-01-01T00:00:00+00:00"}


@pytest.fixture(autouse=True)
def reset_state(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name in (
        "AIOBS_TRACKING_URI",
        "AIOBS_OTLP_ENDPOINT",
        "AIOBS_PROJECT_ID",
        "AIOBS_PROJECT_SLUG",
    ):
        monkeypatch.delenv(name, raising=False)
    _context._reset_for_tests()
    _otel._reset_for_tests()
    yield
    _context._reset_for_tests()
    _otel._reset_for_tests()


class FakeServer:
    def __init__(self, projects: list[dict[str, Any]] | None = None) -> None:
        self.projects = list(projects or [])
        self.created: list[dict[str, Any]] = []
        self.conflict_once_with: dict[str, Any] | None = None

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        path = request.url.path.rstrip("/")
        if request.method == "GET" and path == "/api/v1/projects":
            return httpx2.Response(200, json=self.projects)
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

    def install(self) -> None:
        _context._CLIENT = aiobs.Client(
            "http://test", transport=httpx2.MockTransport(self.handler)
        )


def test_tracking_uri_default_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    assert aiobs.get_tracking_uri() == "http://localhost:8000"
    monkeypatch.setenv("AIOBS_TRACKING_URI", "http://env:2/")
    assert aiobs.get_tracking_uri() == "http://env:2"
    aiobs.set_tracking_uri("http://explicit:3/")
    assert aiobs.get_tracking_uri() == "http://explicit:3"


def test_tracking_uri_drives_client_and_otlp(monkeypatch: pytest.MonkeyPatch) -> None:
    aiobs.set_tracking_uri("http://platform:9000")
    assert aiobs.Client().base_url == "http://platform:9000"
    assert aiobs.get_client().base_url == "http://platform:9000"
    cfg = resolve_config(project_slug="demo")
    assert cfg.endpoint == "http://platform:9000/v1/traces"


def test_otlp_endpoint_env_still_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    aiobs.set_tracking_uri("http://platform:9000")
    monkeypatch.setenv("AIOBS_OTLP_ENDPOINT", "http://collector:4318/v1/traces")
    assert resolve_config(project_slug="demo").endpoint == "http://collector:4318/v1/traces"


def test_get_client_is_shared_and_reset_on_uri_change() -> None:
    first = aiobs.get_client()
    assert aiobs.get_client() is first
    aiobs.set_tracking_uri("http://other:1")
    second = aiobs.get_client()
    assert second is not first
    assert second.base_url == "http://other:1"


def test_set_project_creates_when_missing() -> None:
    server = FakeServer()
    server.install()
    project = aiobs.set_project("HR Assistant")
    assert server.created == [{"name": "HR Assistant", "slug": "hr-assistant"}]
    assert project.slug == "hr-assistant"
    assert aiobs.get_project() == project


def test_set_project_reuses_existing_by_slug() -> None:
    server = FakeServer([_project("p-1", "Whatever", "hr-assistant")])
    server.install()
    project = aiobs.set_project("hr-assistant")
    assert project.id == "p-1"
    assert server.created == []


def test_set_project_reuses_existing_by_name() -> None:
    server = FakeServer([_project("p-1", "HR Assistant", "custom-slug")])
    server.install()
    assert aiobs.set_project("HR Assistant").id == "p-1"
    assert server.created == []


def test_set_project_handles_concurrent_create() -> None:
    server = FakeServer()
    server.conflict_once_with = _project("p-race", "hr-assistant", "hr-assistant")
    server.install()
    assert aiobs.set_project("hr-assistant").id == "p-race"


def test_set_project_rejects_empty() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        aiobs.set_project("  ")


def test_init_uses_active_project(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIOBS_PROJECT_SLUG", "from-env")
    FakeServer([_project("p-1", "hr", "hr")]).install()
    aiobs.set_project("hr")
    cfg = resolve_config()
    assert cfg.project_id == "p-1"
    assert cfg.project_slug is None
    aiobs.init(instrument=False)
    assert _otel._INITIALIZED is True


def test_set_project_after_init_warns(caplog: pytest.LogCaptureFixture) -> None:
    FakeServer([_project("p-1", "a", "a"), _project("p-2", "b", "b")]).install()
    aiobs.set_project("a")
    aiobs.init(instrument=False)
    with caplog.at_level(logging.WARNING, logger="aiobs"):
        aiobs.set_project("b")
    assert any("after init()" in r.message for r in caplog.records)


def test_resources_default_to_active_project() -> None:
    seen: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request.url.path)
        if request.url.path == "/api/v1/projects":
            return httpx2.Response(200, json=[_project("p-1", "hr", "hr")])
        return httpx2.Response(200, json=[])

    _context._CLIENT = aiobs.Client("http://test", transport=httpx2.MockTransport(handler))
    aiobs.set_project("hr")
    client = aiobs.get_client()
    client.datasets.list()
    client.experiments.list()
    client.datasets.list("explicit")
    assert seen[-3:] == [
        "/api/v1/projects/p-1/datasets",
        "/api/v1/projects/p-1/experiments",
        "/api/v1/projects/explicit/datasets",
    ]


def test_resources_fall_back_to_env_project_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIOBS_PROJECT_ID", "env-pid")
    seen: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request.url.path)
        return httpx2.Response(200, json=[])

    client = aiobs.Client("http://test", transport=httpx2.MockTransport(handler))
    client.experiments.list()
    assert seen == ["/api/v1/projects/env-pid/experiments"]


def test_resources_without_project_raise() -> None:
    with pytest.raises(ValueError, match="No project"):
        aiobs.Client("http://test").datasets.list()
