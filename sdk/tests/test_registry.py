from __future__ import annotations

import json
from typing import Any
from urllib.request import Request

import pytest

from aiobs.registry import AppConfigClient


class _FakeHTTPResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeHTTPResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None


@pytest.fixture
def captured_requests() -> list[Request]:
    return []


@pytest.fixture
def mock_urlopen(
    monkeypatch: pytest.MonkeyPatch, captured_requests: list[Request]
) -> None:
    def fake_urlopen(req: Request, timeout: float = 30.0) -> _FakeHTTPResponse:
        captured_requests.append(req)
        method = req.get_method()
        if method == "POST" and req.full_url.endswith("/app-configs"):
            payload = {
                "id": "11111111-1111-1111-1111-111111111111",
                "project_id": "22222222-2222-2222-2222-222222222222",
                "name": "rag-faq",
                "version": 1,
                "description": None,
                "prompt": {"system": "You are helpful."},
                "model": {},
                "retrieval": {},
                "content_hash": "abc",
                "created_at": "2026-01-01T00:00:00+00:00",
            }
            return _FakeHTTPResponse(json.dumps(payload).encode())
        if method == "PUT" and "/app-config-aliases/" in req.full_url:
            payload = {
                "name": "baseline",
                "app_config_id": "11111111-1111-1111-1111-111111111111",
                "updated_at": "2026-01-01T00:00:00+00:00",
                "app_config": {
                    "id": "11111111-1111-1111-1111-111111111111",
                    "name": "rag-faq",
                    "version": 1,
                },
            }
            return _FakeHTTPResponse(json.dumps(payload).encode())
        if method == "GET" and req.full_url.endswith("/app-config-aliases"):
            return _FakeHTTPResponse(json.dumps([]).encode())
        if method == "GET" and "/app-configs" in req.full_url:
            return _FakeHTTPResponse(json.dumps([]).encode())
        raise AssertionError(f"unexpected request: {method} {req.full_url}")

    monkeypatch.setattr("aiobs.registry.urlopen", fake_urlopen)


def test_create_app_config_post_body_and_path(
    mock_urlopen: None,
    captured_requests: list[Request],
) -> None:
    client = AppConfigClient("http://localhost:8000/")
    result = client.create_app_config(
        "proj-1",
        "rag-faq",
        prompt={"system": "You are helpful."},
        description="demo",
    )

    assert result["name"] == "rag-faq"
    assert len(captured_requests) == 1
    req = captured_requests[0]
    assert req.get_method() == "POST"
    assert req.full_url == "http://localhost:8000/api/v1/projects/proj-1/app-configs"
    assert isinstance(req.data, bytes)
    body: dict[str, Any] = json.loads(req.data.decode())
    assert body == {
        "name": "rag-faq",
        "description": "demo",
        "prompt": {"system": "You are helpful."},
    }


def test_set_alias_put_body_and_path(
    mock_urlopen: None,
    captured_requests: list[Request],
) -> None:
    client = AppConfigClient("http://api.example")
    config_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    result = client.set_alias("proj-2", "baseline", config_id)

    assert result["name"] == "baseline"
    req = captured_requests[0]
    assert req.get_method() == "PUT"
    assert (
        req.full_url
        == "http://api.example/api/v1/projects/proj-2/app-config-aliases/baseline"
    )
    assert isinstance(req.data, bytes)
    body = json.loads(req.data.decode())
    assert body == {"app_config_id": config_id}


def test_list_app_configs_query_params(
    monkeypatch: pytest.MonkeyPatch,
    captured_requests: list[Request],
) -> None:
    def fake_urlopen(req: Request, timeout: float = 30.0) -> _FakeHTTPResponse:
        captured_requests.append(req)
        return _FakeHTTPResponse(json.dumps([{"id": "x", "name": "rag-faq"}]).encode())

    monkeypatch.setattr("aiobs.registry.urlopen", fake_urlopen)

    client = AppConfigClient("http://localhost:8000")
    rows = client.list_app_configs("proj-1", name="rag-faq", latest=True)

    assert rows == [{"id": "x", "name": "rag-faq"}]
    req = captured_requests[0]
    assert req.get_method() == "GET"
    assert (
        req.full_url
        == "http://localhost:8000/api/v1/projects/proj-1/app-configs?name=rag-faq&latest=true"
    )


def test_get_aliases_get_path(
    mock_urlopen: None,
    captured_requests: list[Request],
) -> None:
    client = AppConfigClient("http://localhost:8000")
    aliases = client.get_aliases("proj-9")

    assert aliases == []
    req = captured_requests[0]
    assert req.get_method() == "GET"
    assert req.full_url == "http://localhost:8000/api/v1/projects/proj-9/app-config-aliases"
