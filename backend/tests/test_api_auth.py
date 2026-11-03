from __future__ import annotations

import pytest
from httpx2 import AsyncClient

import test_api_evaluation
from opengrade_server.api.auth import (
    SESSION_COOKIE,
    issue_session_token,
    session_token_valid,
)
from opengrade_server.config import Settings, get_settings

client = test_api_evaluation.client  # shared in-memory app fixture

KEY = "og-test-key-0123456789"


@pytest.fixture
def api_key(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("OPENGRADE_API_KEY", KEY)
    monkeypatch.delenv("OPENGRADE_API_KEY_PREVIOUS", raising=False)
    get_settings.cache_clear()
    return KEY


def _bearer(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


@pytest.mark.asyncio
async def test_no_key_configured_keeps_api_open(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENGRADE_API_KEY", raising=False)
    get_settings.cache_clear()

    assert (await client.get("/api/v1/projects")).status_code == 200
    status = await client.get("/api/v1/auth/status")
    assert status.json() == {"auth_required": False, "authenticated": True}


@pytest.mark.asyncio
async def test_key_required_on_api_and_otlp(client: AsyncClient, api_key: str) -> None:
    resp = await client.get("/api/v1/projects")
    assert resp.status_code == 401
    assert resp.headers["www-authenticate"].startswith("Bearer")
    otlp = await client.post(
        "/v1/traces",
        content=b"",
        headers={"content-type": "application/x-protobuf"},
    )
    assert otlp.status_code == 401
    wrong = await client.get("/api/v1/projects", headers=_bearer("nope"))
    assert wrong.status_code == 401


@pytest.mark.asyncio
async def test_bearer_key_is_accepted(client: AsyncClient, api_key: str) -> None:
    resp = await client.get("/api/v1/projects", headers=_bearer(api_key))
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_health_ready_and_status_stay_public(client: AsyncClient, api_key: str) -> None:
    assert (await client.get("/health")).status_code == 200
    status = await client.get("/api/v1/auth/status")
    assert status.status_code == 200
    assert status.json() == {"auth_required": True, "authenticated": False}


@pytest.mark.asyncio
async def test_previous_key_accepted_during_rotation(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENGRADE_API_KEY", "new-key")
    monkeypatch.setenv("OPENGRADE_API_KEY_PREVIOUS", "old-key")
    get_settings.cache_clear()

    for key in ("new-key", "old-key"):
        resp = await client.get("/api/v1/projects", headers=_bearer(key))
        assert resp.status_code == 200, key


@pytest.mark.asyncio
async def test_ui_session_cookie_flow(client: AsyncClient, api_key: str) -> None:
    bad = await client.post("/api/v1/auth/session", json={"api_key": "nope"})
    assert bad.status_code == 401

    resp = await client.post("/api/v1/auth/session", json={"api_key": api_key})
    assert resp.status_code == 204
    set_cookie = resp.headers["set-cookie"]
    assert set_cookie.startswith(f"{SESSION_COOKIE}=")
    assert "HttpOnly" in set_cookie
    assert "samesite=strict" in set_cookie.lower()
    assert api_key not in set_cookie  # the cookie is a signed token, not the key

    assert (await client.get("/api/v1/projects")).status_code == 200
    status = await client.get("/api/v1/auth/status")
    assert status.json() == {"auth_required": True, "authenticated": True}

    logout = await client.delete("/api/v1/auth/session")
    assert logout.status_code == 204
    client.cookies.clear()
    assert (await client.get("/api/v1/projects")).status_code == 401


def test_session_token_expires_and_dies_with_key_rotation() -> None:
    settings = Settings(api_key="k1")
    token, max_age = issue_session_token(settings, now=1_000)
    assert session_token_valid(token, settings, now=1_000 + max_age - 1)
    assert not session_token_valid(token, settings, now=1_000 + max_age)
    assert not session_token_valid(token, Settings(api_key="k2"), now=1_001)
    assert session_token_valid(token, Settings(api_key="k2", api_key_previous="k1"), now=1_001)
    assert not session_token_valid("garbage", settings, now=1_001)
    tampered = f"{1_000 + 10 * max_age}.{token.partition('.')[2]}"
    assert not session_token_valid(tampered, settings, now=1_001)
