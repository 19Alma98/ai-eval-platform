from __future__ import annotations

from collections.abc import Iterator

import httpx2
import pytest

import opengrade
from opengrade import _config, _context, _otel
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
    _config._reset_for_tests()
    _context._reset_for_tests()
    _otel._reset_for_tests()
    yield
    _config._reset_for_tests()
    _context._reset_for_tests()
    _otel._reset_for_tests()


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
    cfg = resolve_config()
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
    cfg = resolve_config()
    assert cfg.project_id == "pid-from-env"
    assert cfg.project_slug is None


def test_resolve_config_rejects_neither() -> None:
    with pytest.raises(ValueError, match="project_id or project_slug"):
        resolve_config()


def test_arg_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENGRADE_PROJECT_SLUG", "from-env")
    cfg = resolve_config(project_slug="from-arg")
    assert cfg.project_slug == "from-arg"


def test_init_records_project_slug_for_resolve_project_id() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.rstrip("/") == "/api/v1/projects":
            return httpx2.Response(
                200,
                json=[
                    {
                        "id": "p-1",
                        "name": "acme",
                        "slug": "acme",
                        "created_at": "2026-01-01T00:00:00+00:00",
                    }
                ],
            )
        return httpx2.Response(404)

    _context._CLIENT = opengrade.Client("http://test", transport=httpx2.MockTransport(handler))
    opengrade.init(project_slug="acme", instrument=False)
    assert _config._ACTIVE_PROJECT_SLUG == "acme"
    assert resolve_project_id() == "p-1"
    assert _config._ACTIVE_PROJECT_ID == "p-1"


def test_init_records_project_id() -> None:
    opengrade.init(project_id="pid-direct", instrument=False)
    assert resolve_project_id() == "pid-direct"
