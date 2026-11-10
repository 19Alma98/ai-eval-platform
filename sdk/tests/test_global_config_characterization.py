"""Instance isolation: settings and clients do not leak across ``Opengrade`` handles."""

from __future__ import annotations

from typing import Any

import httpx2
import pytest
from tests.support.instance import activated, make_og

import opengrade
from opengrade import Opengrade, Settings, current


def _project(pid: str, name: str, slug: str) -> dict[str, Any]:
    return {"id": pid, "name": name, "slug": slug, "created_at": "2026-01-01T00:00:00+00:00"}


def _mock_transport(captured: list[httpx2.Request], host: str) -> httpx2.MockTransport:
    def handler(request: httpx2.Request) -> httpx2.Response:
        captured.append(request)
        if request.url.path.rstrip("/") == "/health":
            return httpx2.Response(200, json={"status": "ok"})
        return httpx2.Response(200, json=[])

    return httpx2.MockTransport(handler)


def test_tracking_uri_from_settings_not_shared() -> None:
    a = make_og(tracking_uri="http://host-a:1", project_id="pa")
    b = make_og(tracking_uri="http://host-b:2", project_id="pb")
    assert a.client.base_url == "http://host-a:1"
    assert b.client.base_url == "http://host-b:2"


def test_resolve_project_id_isolated_per_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENGRADE_PROJECT_ID", raising=False)
    monkeypatch.delenv("OPENGRADE_PROJECT_SLUG", raising=False)

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/by-slug/slug-b"):
            return httpx2.Response(200, json=_project("id-b", "B", "slug-b"))
        return httpx2.Response(404)

    transport = httpx2.MockTransport(handler)
    a = make_og(project_id="id-a")
    b = make_og(project_slug="slug-b")
    b._runtime.client = opengrade.Client("http://test", transport=transport, project_id="id-b")

    from opengrade._config import resolve_project_id

    with activated(a):
        assert resolve_project_id() == "id-a"
    with activated(b):
        assert resolve_project_id() == "id-b"


def test_clients_do_not_cross_instances() -> None:
    cap_a: list[httpx2.Request] = []
    cap_b: list[httpx2.Request] = []
    a = make_og(tracking_uri="http://a", project_id="pa")
    b = make_og(tracking_uri="http://b", project_id="pb")
    a._runtime.client = opengrade.Client(
        "http://a", transport=_mock_transport(cap_a, "a"), project_id="pa"
    )
    b._runtime.client = opengrade.Client(
        "http://b", transport=_mock_transport(cap_b, "b"), project_id="pb"
    )

    with activated(a):
        a.client.health()
    with activated(b):
        b.client.health()

    assert cap_a and cap_b
    assert all(r.url.host == "a" for r in cap_a)
    assert all(r.url.host == "b" for r in cap_b)
    assert a.client is not b.client


def test_api_key_change_rebuilds_only_that_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENGRADE_API_KEY", "env-key")
    og = Opengrade(Settings.from_env(project_id="p1"))
    first = og.client
    og2 = Opengrade(Settings(tracking_uri=og.client.base_url, api_key="other-key", project_id="p2"))
    assert og2.client is not first
    with activated(og2):
        assert current() is og2
