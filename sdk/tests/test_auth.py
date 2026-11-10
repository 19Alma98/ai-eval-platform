from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

import httpx2
import pytest
from tests.support.instance import init_og
from tests.support.reset import reset_sdk

import opengrade
from opengrade import Opengrade, Settings
from opengrade._config import auth_headers
from opengrade._http import _HttpTransport


@pytest.fixture(autouse=True)
def reset_state(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv("OPENGRADE_API_KEY", raising=False)
    monkeypatch.delenv("OPENGRADE_PROJECT_ID", raising=False)
    monkeypatch.delenv("OPENGRADE_PROJECT_SLUG", raising=False)
    monkeypatch.delenv("OPENGRADE_DISABLED", raising=False)
    reset_sdk(otel=True)
    yield
    reset_sdk(otel=True)


def test_no_key_sends_no_header() -> None:
    og = Opengrade(Settings())
    assert auth_headers("http://localhost:8000", runtime=og._runtime) == {}


def test_key_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENGRADE_API_KEY", " env-key ")
    og = Opengrade(Settings.from_env())
    assert og.settings.api_key == "env-key"
    og2 = Opengrade(Settings(api_key="set-key", project_id="p1"))
    assert auth_headers("https://og.example.com", runtime=og2._runtime) == {
        "Authorization": "Bearer set-key"
    }
    og3 = Opengrade(Settings.from_env(project_id="p1"))
    assert og3.settings.api_key == "env-key"


def test_transport_sends_bearer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENGRADE_API_KEY", "env-key")
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json=[])

    transport = _HttpTransport("http://localhost:8000", transport=httpx2.MockTransport(handler))
    transport.request("GET", "/api/v1/projects")
    explicit = _HttpTransport(
        "http://localhost:8000", transport=httpx2.MockTransport(handler), api_key="arg-key"
    )
    explicit.request("GET", "/api/v1/projects")
    assert seen[0].headers["authorization"] == "Bearer env-key"
    assert seen[1].headers["authorization"] == "Bearer arg-key"
    transport.close()
    explicit.close()


def test_client_api_key_argument() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json={"status": "ok"})

    with opengrade.Client(
        "http://localhost:8000", api_key="client-key", transport=httpx2.MockTransport(handler)
    ) as client:
        client.health()
    assert seen[0].headers["authorization"] == "Bearer client-key"


def test_plain_http_to_remote_host_warns_once(caplog: pytest.LogCaptureFixture) -> None:
    og = Opengrade(Settings(project_id="p1"))
    with caplog.at_level(logging.WARNING, logger="opengrade"):
        auth_headers("http://localhost:8000", "k", runtime=og._runtime)
        assert "plain HTTP" not in caplog.text
        auth_headers("http://og.internal:8000", "k", runtime=og._runtime)
        auth_headers("http://og.internal:8000", "k", runtime=og._runtime)
        auth_headers("https://og.example.com", "k", runtime=og._runtime)
    assert caplog.text.count("plain HTTP") == 1


def test_otlp_exporter_gets_bearer(monkeypatch: pytest.MonkeyPatch) -> None:
    from opentelemetry.exporter.otlp.proto.http import trace_exporter

    captured: dict[str, Any] = {}
    real = trace_exporter.OTLPSpanExporter

    def fake_exporter(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(trace_exporter, "OTLPSpanExporter", fake_exporter)
    monkeypatch.setenv("OPENGRADE_API_KEY", "otlp-key")

    init_og(project_slug="demo", instrument=False)

    assert captured["headers"]["Authorization"] == "Bearer otlp-key"
    assert captured["headers"]["X-Project-Slug"] == "demo"
