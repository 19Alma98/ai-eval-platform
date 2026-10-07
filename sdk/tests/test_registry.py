from __future__ import annotations

import json
from typing import Any

import httpx2
import pytest

from aiobs.registry import AppConfigClient


@pytest.fixture
def captured_requests() -> list[httpx2.Request]:
    return []


@pytest.fixture
def mock_transport(captured_requests: list[httpx2.Request]) -> httpx2.MockTransport:
    def handler(request: httpx2.Request) -> httpx2.Response:
        captured_requests.append(request)
        method = request.method
        url = str(request.url)
        if method == "POST" and url.endswith("/app-configs"):
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
            return httpx2.Response(201, json=payload)
        if method == "PUT" and "/app-config-aliases/" in url:
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
            return httpx2.Response(200, json=payload)
        if method == "GET" and url.endswith("/app-config-aliases"):
            return httpx2.Response(200, json=[])
        if method == "GET" and "/app-configs" in url:
            return httpx2.Response(200, json=[])
        raise AssertionError(f"unexpected request: {method} {url}")

    return httpx2.MockTransport(handler)


def test_create_app_config_post_body_and_path(
    mock_transport: httpx2.MockTransport,
    captured_requests: list[httpx2.Request],
) -> None:
    client = AppConfigClient("http://localhost:8000/", transport=mock_transport)
    result = client.create_app_config(
        "proj-1",
        "rag-faq",
        prompt={"system": "You are helpful."},
        description="demo",
    )

    assert result["name"] == "rag-faq"
    assert len(captured_requests) == 1
    req = captured_requests[0]
    assert req.method == "POST"
    assert str(req.url) == "http://localhost:8000/api/v1/projects/proj-1/app-configs"
    body: dict[str, Any] = json.loads(req.content.decode())
    assert body == {
        "name": "rag-faq",
        "description": "demo",
        "prompt": {"system": "You are helpful."},
    }


def test_set_alias_put_body_and_path(
    mock_transport: httpx2.MockTransport,
    captured_requests: list[httpx2.Request],
) -> None:
    client = AppConfigClient("http://api.example", transport=mock_transport)
    config_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    result = client.set_alias("proj-2", "baseline", config_id)

    assert result["name"] == "baseline"
    req = captured_requests[0]
    assert req.method == "PUT"
    assert str(req.url) == ("http://api.example/api/v1/projects/proj-2/app-config-aliases/baseline")
    body = json.loads(req.content.decode())
    assert body == {"app_config_id": config_id}


def test_list_app_configs_query_params(
    captured_requests: list[httpx2.Request],
) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        captured_requests.append(request)
        return httpx2.Response(200, json=[{"id": "x", "name": "rag-faq"}])

    client = AppConfigClient(
        "http://localhost:8000",
        transport=httpx2.MockTransport(handler),
    )
    rows = client.list_app_configs("proj-1", name="rag-faq", latest=True)

    assert rows == [{"id": "x", "name": "rag-faq"}]
    req = captured_requests[0]
    assert req.method == "GET"
    assert str(req.url) == (
        "http://localhost:8000/api/v1/projects/proj-1/app-configs?name=rag-faq&latest=true"
    )


def test_get_aliases_get_path(
    mock_transport: httpx2.MockTransport,
    captured_requests: list[httpx2.Request],
) -> None:
    client = AppConfigClient("http://localhost:8000", transport=mock_transport)
    aliases = client.get_aliases("proj-9")

    assert aliases == []
    req = captured_requests[0]
    assert req.method == "GET"
    assert str(req.url) == ("http://localhost:8000/api/v1/projects/proj-9/app-config-aliases")
