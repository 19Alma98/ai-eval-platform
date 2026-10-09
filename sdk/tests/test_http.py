from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx2
import pytest

from aiobs._http import AiobsAPIError, _HttpTransport, read_upload, resolve_api_base_url


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


def test_request_raises_aiobs_api_error() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(404, text='{"detail":"missing"}')

    transport = _HttpTransport(
        "http://localhost:8000",
        transport=httpx2.MockTransport(handler),
    )
    with pytest.raises(AiobsAPIError) as exc_info:
        transport.request("GET", "/api/v1/projects/missing")
    assert exc_info.value.status == 404
    assert "missing" in exc_info.value.body
    assert exc_info.value.detail == "missing"
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
    monkeypatch.delenv("AIOBS_API_BASE_URL", raising=False)
    monkeypatch.delenv("AIOBS_BASE_URL", raising=False)
    assert resolve_api_base_url() == "http://localhost:8000"
    assert resolve_api_base_url("http://x/") == "http://x"
    monkeypatch.setenv("AIOBS_API_BASE_URL", "http://from-api/")
    assert resolve_api_base_url() == "http://from-api"
    monkeypatch.delenv("AIOBS_API_BASE_URL")
    monkeypatch.setenv("AIOBS_BASE_URL", "http://legacy/")
    assert resolve_api_base_url() == "http://legacy"


def test_read_upload(tmp_path: Path) -> None:
    path = tmp_path / "items.csv"
    path.write_bytes(b"a,b\n")
    assert read_upload(path) == ("items.csv", b"a,b\n")
    assert read_upload(file=("x.csv", b"z")) == ("x.csv", b"z")
    with pytest.raises(ValueError):
        read_upload(path, file=("x.csv", b"z"))
    with pytest.raises(ValueError):
        read_upload()
