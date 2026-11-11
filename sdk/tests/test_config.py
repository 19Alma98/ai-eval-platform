from __future__ import annotations

from collections.abc import Iterator

import httpx2
import pytest
from tests.support.instance import activated, make_og
from tests.support.reset import reset_sdk

import opengrade
from opengrade import Settings
from opengrade._config import project_headers, resolve_config, resolve_project_id


@pytest.fixture(autouse=True)
def reset_config_state(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name in (
        "OPENGRADE_PROJECT_ID",
        "OPENGRADE_PROJECT_SLUG",
        "OPENGRADE_OTLP_ENDPOINT",
        "OPENGRADE_SERVICE_NAME",
        "OPENGRADE_TRACKING_URI",
    ):
        monkeypatch.delenv(name, raising=False)
    reset_sdk(otel=True)
    yield
    reset_sdk(otel=True)


def test_resolve_config_from_project_slug_arg() -> None:
    cfg = resolve_config(project_slug="demo")
    assert cfg.project_slug == "demo"
    assert cfg.project_id is None
    assert cfg.endpoint == "http://localhost:8000/v1/traces"
    assert cfg.service_name == "opengrade-app"
    assert project_headers(cfg) == {"X-Project-Slug": "demo"}


def test_resolve_config_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENGRADE_PROJECT_ID", "11111111-1111-1111-1111-111111111111")
    monkeypatch.setenv("OPENGRADE_OTLP_ENDPOINT", "http://api:8000/v1/traces")
    monkeypatch.setenv("OPENGRADE_SERVICE_NAME", "my-svc")
    cfg = resolve_config(settings=Settings.from_env())
    assert cfg.project_id == "11111111-1111-1111-1111-111111111111"
    assert cfg.endpoint == "http://api:8000/v1/traces"
    assert cfg.service_name == "my-svc"
    assert project_headers(cfg) == {"X-Project-Id": "11111111-1111-1111-1111-111111111111"}


def test_resolve_config_rejects_both_args() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        resolve_config(project_id="abc", project_slug="demo")


def test_resolve_config_dual_env_id_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENGRADE_PROJECT_ID", "pid-from-env")
    monkeypatch.setenv("OPENGRADE_PROJECT_SLUG", "slug-from-env")
    cfg = resolve_config(settings=Settings.from_env())
    assert cfg.project_id == "pid-from-env"
    assert cfg.project_slug is None


def test_resolve_config_rejects_neither() -> None:
    with pytest.raises(ValueError, match="no project configured"):
        resolve_config()


def test_arg_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENGRADE_PROJECT_SLUG", "from-env")
    cfg = resolve_config(project_slug="from-arg")
    assert cfg.project_slug == "from-arg"


def test_init_records_project_slug_for_resolve_project_id() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/by-slug/acme"):
            return httpx2.Response(
                200,
                json={
                    "id": "p-1",
                    "name": "acme",
                    "slug": "acme",
                    "created_at": "2026-01-01T00:00:00+00:00",
                },
            )
        return httpx2.Response(404)

    og = make_og(project_slug="acme")
    og._runtime.client = opengrade.Client("http://test", transport=httpx2.MockTransport(handler))
    with activated(og):
        og.init_tracing(instrument=False)
        assert og.settings.project_slug == "acme"
        assert resolve_project_id() == "p-1"
        assert og.settings.project_id == "p-1"


def test_init_records_project_id() -> None:
    og = make_og(project_id="pid-direct")
    with activated(og):
        og.init_tracing(instrument=False)
        assert resolve_project_id() == "pid-direct"


def test_lazy_resolve_slug_negative_cache_skips_second_lookup() -> None:
    calls: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(str(request.url.path))
        if request.url.path.endswith("/by-slug/missing"):
            return httpx2.Response(404, json={"detail": "not found"})
        return httpx2.Response(404)

    og = make_og(project_slug="missing")
    og._runtime.client = opengrade.Client("http://test", transport=httpx2.MockTransport(handler))
    with activated(og):
        og.init_tracing(instrument=False)

        with pytest.raises(ValueError, match="No project"):
            resolve_project_id()
        with pytest.raises(ValueError, match="No project"):
            resolve_project_id()

    assert calls.count("/api/v1/projects/by-slug/missing") == 1


def test_lazy_resolve_slug_clears_negative_cache_on_set_project() -> None:
    calls: list[str] = []
    projects = {
        "ok": {
            "id": "p-ok",
            "name": "ok",
            "slug": "ok",
            "created_at": "2026-01-01T00:00:00+00:00",
        }
    }

    def handler(request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        calls.append(path)
        if path.endswith("/by-slug/missing"):
            return httpx2.Response(404, json={"detail": "not found"})
        if path.endswith("/by-slug/ok"):
            return httpx2.Response(200, json=projects["ok"])
        if path.rstrip("/") == "/api/v1/projects" and request.method == "GET":
            return httpx2.Response(200, json=[projects["ok"]])
        return httpx2.Response(404)

    og = make_og(project_slug="missing")
    og._runtime.client = opengrade.Client("http://test", transport=httpx2.MockTransport(handler))
    with activated(og):
        og.init_tracing(instrument=False)
        with pytest.raises(ValueError):
            resolve_project_id()

        og.set_project("ok")
        assert resolve_project_id() == "p-ok"


def test_lazy_resolve_connection_error_not_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls["n"] += 1
        raise httpx2.ConnectError("boom", request=request)

    monkeypatch.setattr("opengrade._http._BACKOFF_BASE_S", 0.0)
    monkeypatch.setattr("opengrade._http.time.sleep", lambda _s: None)
    og = make_og(project_slug="flaky")
    og._runtime.client = opengrade.Client("http://test", transport=httpx2.MockTransport(handler))
    with activated(og):
        og.init_tracing(instrument=False)

        with pytest.raises(ValueError):
            resolve_project_id()
        with pytest.raises(ValueError):
            resolve_project_id()
    assert calls["n"] >= 2


def test_get_by_slug_success_via_resolve() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/by-slug/acme"):
            return httpx2.Response(
                200,
                json={
                    "id": "p-1",
                    "name": "acme",
                    "slug": "acme",
                    "created_at": "2026-01-01T00:00:00+00:00",
                },
            )
        return httpx2.Response(404)

    og = make_og(project_slug="acme")
    og._runtime.client = opengrade.Client("http://test", transport=httpx2.MockTransport(handler))
    with activated(og):
        og.init_tracing(instrument=False)
        assert resolve_project_id() == "p-1"
        assert resolve_project_id() == "p-1"
