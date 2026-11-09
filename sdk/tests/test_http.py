from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx2
import pytest

import opengrade._http as http_mod
from opengrade._http import (
    OpengradeAPIError,
    OpengradeConnectionError,
    OpengradeError,
    _HttpTransport,
    _retry_decision,
    read_upload,
    resolve_api_base_url,
)


def test_request_json_post_and_get() -> None:
    captured: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured.append(request)
        if request.method == "POST":
            return httpx2.Response(200, json={"ok": True})
        return httpx2.Response(200, json=[1, 2])

    transport = _HttpTransport(
        "http://localhost:8000/",
        timeout=12.0,
        transport=httpx2.MockTransport(handler),
    )

    created = transport.request("POST", "/api/v1/projects", body={"name": "Demo"})
    assert created == {"ok": True}
    assert str(captured[0].url) == "http://localhost:8000/api/v1/projects"
    assert captured[0].headers["content-type"] == "application/json"
    body: dict[str, Any] = json.loads(captured[0].content.decode())
    assert body == {"name": "Demo"}

    listed = transport.request("GET", "/api/v1/projects", query={"x": "1"})
    assert listed == [1, 2]
    assert str(captured[1].url) == "http://localhost:8000/api/v1/projects?x=1"
    transport.close()


def test_request_empty_body_returns_none() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(204)

    transport = _HttpTransport(
        "http://localhost:8000",
        transport=httpx2.MockTransport(handler),
    )
    assert transport.request("DELETE", "/api/v1/projects/x") is None
    transport.close()


def test_request_raises_opengrade_api_error() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(404, text='{"detail":"missing"}')

    transport = _HttpTransport(
        "http://localhost:8000",
        transport=httpx2.MockTransport(handler),
    )
    with pytest.raises(OpengradeAPIError) as exc_info:
        transport.request("GET", "/api/v1/projects/missing")
    assert exc_info.value.status == 404
    assert "missing" in exc_info.value.body
    assert exc_info.value.detail == "missing"
    assert isinstance(exc_info.value, OpengradeError)
    transport.close()


def test_retry_decision_idempotent_statuses_and_methods() -> None:
    assert _retry_decision("GET", attempt=0, status=429)[0] is True
    assert _retry_decision("GET", attempt=0, status=503)[0] is True
    assert _retry_decision("GET", attempt=0, status=500)[0] is False
    assert _retry_decision("POST", attempt=0, status=503)[0] is False
    assert _retry_decision("GET", attempt=2, status=503)[0] is False  # 3rd attempt index → no more


def test_retry_decision_retry_after_seconds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(http_mod, "_RETRY_AFTER_CAP_S", 30.0)
    should, delay = _retry_decision("GET", attempt=0, status=429, retry_after="2")
    assert should is True
    assert delay == 2.0


def test_retry_decision_retry_after_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(http_mod, "_RETRY_AFTER_CAP_S", 5.0)
    should, delay = _retry_decision("GET", attempt=0, status=503, retry_after="99")
    assert should is True
    assert delay == 5.0


def test_retry_decision_transport_uses_jitter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(http_mod, "_BACKOFF_BASE_S", 0.5)
    monkeypatch.setattr(http_mod.random, "uniform", lambda a, b: b)
    should, delay = _retry_decision("GET", attempt=1, transport_error=True)
    assert should is True
    assert delay == 1.0  # base * 2**1


def test_get_retries_503_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(http_mod, "_BACKOFF_BASE_S", 0.0)
    sleeps: list[float] = []
    monkeypatch.setattr(http_mod.time, "sleep", sleeps.append)
    calls = {"n": 0}

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx2.Response(503, text="busy")
        return httpx2.Response(200, json={"ok": True})

    transport = _HttpTransport(
        "http://localhost:8000",
        transport=httpx2.MockTransport(handler),
    )
    assert transport.request("GET", "/api/v1/projects") == {"ok": True}
    assert calls["n"] == 3
    assert len(sleeps) == 2
    transport.close()


def test_get_honors_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(http_mod.time, "sleep", sleeps.append)
    calls = {"n": 0}

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx2.Response(429, headers={"Retry-After": "3"}, text="slow")
        return httpx2.Response(200, json=[])

    transport = _HttpTransport(
        "http://localhost:8000",
        transport=httpx2.MockTransport(handler),
    )
    assert transport.request("GET", "/api/v1/projects") == []
    assert sleeps == [3.0]
    transport.close()


def test_post_does_not_retry_503(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(http_mod, "_BACKOFF_BASE_S", 0.0)
    calls = {"n": 0}

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls["n"] += 1
        return httpx2.Response(503, text="busy")

    transport = _HttpTransport(
        "http://localhost:8000",
        transport=httpx2.MockTransport(handler),
    )
    with pytest.raises(OpengradeAPIError) as exc_info:
        transport.request("POST", "/api/v1/projects", body={"name": "x"})
    assert exc_info.value.status == 503
    assert calls["n"] == 1
    transport.close()


def test_get_exhausted_503_raises_api_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(http_mod, "_BACKOFF_BASE_S", 0.0)
    monkeypatch.setattr(http_mod.time, "sleep", lambda _s: None)

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(503, text="busy")

    transport = _HttpTransport(
        "http://localhost:8000",
        transport=httpx2.MockTransport(handler),
    )
    with pytest.raises(OpengradeAPIError) as exc_info:
        transport.request("GET", "/api/v1/projects")
    assert exc_info.value.status == 503
    transport.close()


def test_request_wraps_connect_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(http_mod, "_BACKOFF_BASE_S", 0.0)

    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("boom", request=request)

    transport = _HttpTransport(
        "http://localhost:8000",
        transport=httpx2.MockTransport(handler),
    )
    with pytest.raises(OpengradeConnectionError, match="platform unreachable"):
        transport.request("GET", "/api/v1/projects")
    transport.close()


def test_request_multipart() -> None:
    captured: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured.append(request)
        return httpx2.Response(200, json={"created": 2, "errors": []})

    transport = _HttpTransport(
        "http://api.example",
        transport=httpx2.MockTransport(handler),
    )
    result = transport.request_multipart(
        "POST",
        "/api/v1/datasets/ds-1/items/import",
        file_field="file",
        filename="gold.csv",
        content=b"question,expected_answer\nQ?,A\n",
        content_type="text/csv",
        query={"format": "csv"},
    )
    assert result == {"created": 2, "errors": []}
    req = captured[0]
    assert req.method == "POST"
    assert str(req.url) == ("http://api.example/api/v1/datasets/ds-1/items/import?format=csv")
    ctype = req.headers.get("content-type")
    assert ctype is not None
    assert ctype.startswith("multipart/form-data")
    assert b"gold.csv" in req.content
    assert b"question,expected_answer" in req.content
    transport.close()


def test_resolve_api_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENGRADE_TRACKING_URI", raising=False)
    assert resolve_api_base_url() == "http://localhost:8000"
    assert resolve_api_base_url("http://x/") == "http://x"
    monkeypatch.setenv("OPENGRADE_TRACKING_URI", "http://from-env/")
    assert resolve_api_base_url() == "http://from-env"


def test_read_upload(tmp_path: Path) -> None:
    path = tmp_path / "items.csv"
    path.write_bytes(b"a,b\n")
    assert read_upload(path) == ("items.csv", b"a,b\n")
    assert read_upload(file=("x.csv", b"z")) == ("x.csv", b"z")
    with pytest.raises(ValueError):
        read_upload(path, file=("x.csv", b"z"))
    with pytest.raises(ValueError):
        read_upload()
