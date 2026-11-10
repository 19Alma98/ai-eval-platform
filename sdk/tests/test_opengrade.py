from __future__ import annotations

import json
from typing import Any

import httpx2
import pytest
from tests.support.reset import reset_sdk

import opengrade
from opengrade import Opengrade, Settings, current


@pytest.fixture(autouse=True)
def reset_state() -> None:
    reset_sdk(otel=False)
    yield
    reset_sdk(otel=False)


def _project(pid: str, name: str, slug: str) -> dict[str, Any]:
    return {"id": pid, "name": name, "slug": slug, "created_at": "2026-01-01T00:00:00+00:00"}


def _mock_transport(captured: list[httpx2.Request], label: str) -> httpx2.MockTransport:
    def handler(request: httpx2.Request) -> httpx2.Response:
        captured.append(request)
        path = request.url.path.rstrip("/")
        if request.method == "GET" and path == "/api/v1/projects":
            return httpx2.Response(200, json=[])
        if request.method == "POST" and path == "/api/v1/projects":
            body = json.loads(request.content)
            return httpx2.Response(
                201,
                json=_project(f"proj-{label}", body["name"], body["slug"]),
            )
        return httpx2.Response(404, json={"detail": "not found"})

    return httpx2.MockTransport(handler)


def test_instances_isolate_control_plane_calls() -> None:
    cap_a: list[httpx2.Request] = []
    cap_b: list[httpx2.Request] = []
    a = Opengrade(settings=Settings(tracking_uri="http://host-a", project_id="proj-a"))
    b = Opengrade(settings=Settings(tracking_uri="http://host-b", project_id="proj-b"))
    a._runtime.client = opengrade.Client(
        "http://host-a", transport=_mock_transport(cap_a, "a"), project_id="proj-a"
    )
    b._runtime.client = opengrade.Client(
        "http://host-b", transport=_mock_transport(cap_b, "b"), project_id="proj-b"
    )

    with a.activate():
        a.client.projects.list()
    with b.activate():
        b.client.projects.list()

    assert cap_a and cap_b
    assert all("host-a" in str(r.url) for r in cap_a)
    assert all("host-b" in str(r.url) for r in cap_b)


def test_activate_sets_current_and_restores() -> None:
    with pytest.raises(RuntimeError, match="No active Opengrade"):
        current()
    default = Opengrade(settings=Settings(tracking_uri="http://default"))
    other = Opengrade(settings=Settings(tracking_uri="http://other"))
    with default.activate():
        assert current() is default
        with other.activate():
            assert current() is other
        assert current() is default


def test_set_project_inside_activate_targets_active_instance() -> None:
    cap_default: list[httpx2.Request] = []
    cap_active: list[httpx2.Request] = []
    default = Opengrade(settings=Settings(tracking_uri="http://default", project_id="proj-default"))
    default._runtime.client = opengrade.Client(
        "http://default",
        transport=_mock_transport(cap_default, "default"),
        project_id="proj-default",
    )

    active = Opengrade(settings=Settings(tracking_uri="http://active", project_id="proj-active"))
    active._runtime.client = opengrade.Client(
        "http://active",
        transport=_mock_transport(cap_active, "active"),
        project_id="proj-active",
    )

    with active.activate():
        active.set_project("ActiveProject")

    assert cap_active and not cap_default
    assert active._runtime.settings.project_id == "proj-active"
    assert active._runtime.active_project is not None
    assert active._runtime.active_project.name == "ActiveProject"


def test_client_uses_active_instance_in_activate() -> None:
    seen: list[str] = []

    @opengrade.trace
    def work() -> None:
        seen.append(current().client.base_url)

    active = Opengrade(settings=Settings(tracking_uri="http://trace-host"))
    active._runtime.client = opengrade.Client("http://trace-host", project_id="p1")
    with active.activate():
        work()
    assert seen == ["http://trace-host"]
