from __future__ import annotations

import pytest
from aiobs._config import project_headers, resolve_config


def test_resolve_config_from_project_slug_arg(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AIOBS_PROJECT_ID", raising=False)
    monkeypatch.delenv("AIOBS_PROJECT_SLUG", raising=False)
    cfg = resolve_config(project_slug="demo")
    assert cfg.project_slug == "demo"
    assert cfg.project_id is None
    assert cfg.endpoint == "http://localhost:8000/v1/traces"
    assert cfg.service_name == "aiobs-app"
    assert project_headers(cfg) == {"X-Project-Slug": "demo"}


def test_resolve_config_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIOBS_PROJECT_ID", "11111111-1111-1111-1111-111111111111")
    monkeypatch.delenv("AIOBS_PROJECT_SLUG", raising=False)
    monkeypatch.setenv("AIOBS_OTLP_ENDPOINT", "http://api:8000/v1/traces")
    monkeypatch.setenv("AIOBS_SERVICE_NAME", "my-svc")
    cfg = resolve_config()
    assert cfg.project_id == "11111111-1111-1111-1111-111111111111"
    assert cfg.endpoint == "http://api:8000/v1/traces"
    assert cfg.service_name == "my-svc"
    assert project_headers(cfg) == {
        "X-Project-Id": "11111111-1111-1111-1111-111111111111"
    }


def test_resolve_config_rejects_both(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AIOBS_PROJECT_ID", raising=False)
    monkeypatch.delenv("AIOBS_PROJECT_SLUG", raising=False)
    with pytest.raises(ValueError, match="exactly one"):
        resolve_config(project_id="abc", project_slug="demo")


def test_resolve_config_rejects_neither(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AIOBS_PROJECT_ID", raising=False)
    monkeypatch.delenv("AIOBS_PROJECT_SLUG", raising=False)
    with pytest.raises(ValueError, match="exactly one"):
        resolve_config()


def test_arg_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIOBS_PROJECT_SLUG", "from-env")
    monkeypatch.delenv("AIOBS_PROJECT_ID", raising=False)
    cfg = resolve_config(project_slug="from-arg")
    assert cfg.project_slug == "from-arg"
