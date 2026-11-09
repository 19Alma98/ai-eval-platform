"""Characterization tests for process-wide opengrade config (global state).

Locks precedence and cross-subsystem behavior before refactors remove module globals.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx2
import pytest

import opengrade
from opengrade import _config, _context, _otel
from opengrade._config import resolve_config, resolve_project_id


@pytest.fixture(autouse=True)
def reset_globals(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name in (
        "OPENGRADE_API_KEY",
        "OPENGRADE_PROJECT_ID",
        "OPENGRADE_PROJECT_SLUG",
        "OPENGRADE_OTLP_ENDPOINT",
        "OPENGRADE_SERVICE_NAME",
        "OPENGRADE_TRACKING_URI",
    ):
        monkeypatch.delenv(name, raising=False)
    _config._reset_for_tests()
    _context._reset_for_tests()
    _otel._reset_for_tests()
    yield
    _config._reset_for_tests()
    _context._reset_for_tests()
    _otel._reset_for_tests()


def _project(pid: str, name: str, slug: str) -> dict[str, Any]:
    return {"id": pid, "name": name, "slug": slug, "created_at": "2026-01-01T00:00:00+00:00"}


class FakeServer:
    def __init__(self, projects: list[dict[str, Any]] | None = None) -> None:
        self.projects = list(projects or [])

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        path = request.url.path.rstrip("/")
        if request.method == "GET" and path.startswith("/api/v1/projects/by-slug/"):
            slug = path.removeprefix("/api/v1/projects/by-slug/")
            for p in self.projects:
                if p["slug"] == slug:
                    return httpx2.Response(200, json=p)
            return httpx2.Response(404, json={"detail": "not found"})
        if request.method == "GET" and path == "/api/v1/projects":
            projects = self.projects
            slug = request.url.params.get("slug")
            if slug is not None:
                projects = [p for p in projects if p["slug"] == slug]
            return httpx2.Response(200, json=projects)
        if request.method == "GET" and path == "/health":
            return httpx2.Response(200, json={"status": "ok"})
        return httpx2.Response(404, json={"detail": "not found"})

    def install(self) -> None:
        transport = httpx2.MockTransport(self.handler)
        _context._CLIENT = opengrade.Client("http://test", transport=transport)


def _project_headers_from_otlp_captures(
    captures: list[dict[str, str]],
) -> dict[str, str]:
    headers = captures[-1]
    return {k: v for k, v in headers.items() if k.lower().startswith("x-project")}


def test_tracking_uri_precedence_explicit_over_env_over_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert opengrade.get_tracking_uri() == "http://localhost:8000"
    monkeypatch.setenv("OPENGRADE_TRACKING_URI", "http://from-env:1")
    assert opengrade.get_tracking_uri() == "http://from-env:1"
    opengrade.set_tracking_uri("http://from-setter:2")
    assert opengrade.get_tracking_uri() == "http://from-setter:2"


def test_resolve_config_vs_resolve_project_id_when_only_env_slug(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENGRADE_PROJECT_SLUG", "demo-slug")
    FakeServer([_project("resolved-id", "Demo", "demo-slug")]).install()

    cfg = resolve_config()
    assert cfg.project_slug == "demo-slug"
    assert cfg.project_id is None

    assert resolve_project_id() == "resolved-id"


def test_resolve_config_id_wins_over_slug_when_both_in_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENGRADE_PROJECT_ID", "pid-env")
    monkeypatch.setenv("OPENGRADE_PROJECT_SLUG", "slug-env")
    cfg = resolve_config()
    assert cfg.project_id == "pid-env"
    assert cfg.project_slug is None
    assert resolve_project_id() == "pid-env"


def test_get_client_rebuilt_after_set_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENGRADE_API_KEY", "first-key")
    seen: list[str] = []
    RealClient = _context.Client

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request.headers.get("authorization", ""))
        return httpx2.Response(200, json={"status": "ok"})

    def client_with_mock(*args: Any, **kwargs: Any) -> opengrade.Client:
        kwargs.setdefault("transport", httpx2.MockTransport(handler))
        return RealClient(*args, **kwargs)

    monkeypatch.setattr(_context, "Client", client_with_mock)

    first = opengrade.get_client()
    first.health()
    assert seen[-1] == "Bearer first-key"

    opengrade.set_api_key("second-key")
    second = opengrade.get_client()
    assert second is not first
    second.health()
    assert seen[-1] == "Bearer second-key"


def test_set_project_after_init_updates_control_plane_not_otlp_until_force(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opentelemetry.exporter.otlp.proto.http import trace_exporter

    otlp_headers_captures: list[dict[str, str]] = []
    real_exporter = trace_exporter.OTLPSpanExporter

    def recording_exporter(**kwargs: Any) -> Any:
        headers = dict(kwargs.get("headers") or {})
        otlp_headers_captures.append(headers)
        return real_exporter(**kwargs)

    monkeypatch.setattr(trace_exporter, "OTLPSpanExporter", recording_exporter)

    FakeServer([_project("p-1", "a", "a"), _project("p-2", "b", "b")]).install()
    opengrade.set_project("a")
    opengrade.init(instrument=False)
    assert _project_headers_from_otlp_captures(otlp_headers_captures) == {"X-Project-Id": "p-1"}
    assert resolve_project_id() == "p-1"

    opengrade.set_project("b")
    assert opengrade.get_project() is not None
    assert opengrade.get_project().id == "p-2"
    assert resolve_project_id() == "p-2"
    # OTLP exporter headers are fixed at init time.
    assert len(otlp_headers_captures) == 1
    assert _project_headers_from_otlp_captures(otlp_headers_captures) == {"X-Project-Id": "p-1"}

    opengrade.init(force=True, instrument=False)
    assert len(otlp_headers_captures) == 2
    assert _project_headers_from_otlp_captures(otlp_headers_captures) == {"X-Project-Id": "p-2"}
    assert resolve_project_id() == "p-2"
