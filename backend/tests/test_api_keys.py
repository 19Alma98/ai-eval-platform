"""Per-client API keys and scopes, on a real SQLite database."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
from httpx2 import ASGITransport, AsyncClient

from opengrade_server.config import get_settings
from opengrade_server.infrastructure.db import bootstrap_schema, dispose_db, init_db
from opengrade_server.main import create_app

ENV_KEY = "env-admin-key-0123456789"


def _bearer(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


@pytest.fixture
async def client(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[AsyncClient]:
    db_path = tmp_path_factory.mktemp("api_keys") / "opengrade.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("OPENGRADE_API_KEY", ENV_KEY)
    get_settings.cache_clear()
    await dispose_db()
    init_db(get_settings())
    await bootstrap_schema()
    app = create_app(mount_packaged_ui=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await dispose_db()
    os.environ.pop("DATABASE_URL", None)
    get_settings.cache_clear()


async def _create_key(client: AsyncClient, scope: str, name: str | None = None) -> dict:
    resp = await client.post(
        "/api/v1/api-keys",
        json={"name": name or f"{scope} key", "scope": scope},
        headers=_bearer(ENV_KEY),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_create_list_never_returns_key_again(client: AsyncClient) -> None:
    created = await _create_key(client, "ingest", "prod chatbot")
    assert created["key"].startswith("og_")
    assert created["prefix"] == created["key"][:10]

    listed = await client.get("/api/v1/api-keys", headers=_bearer(ENV_KEY))
    assert listed.status_code == 200
    (row,) = listed.json()
    assert row["name"] == "prod chatbot"
    assert row["scope"] == "ingest"
    assert "key" not in row
    assert created["key"] not in listed.text


@pytest.mark.asyncio
async def test_ingest_scope(client: AsyncClient) -> None:
    key = (await _create_key(client, "ingest"))["key"]
    project = await client.post("/api/v1/projects", json={"name": "p"}, headers=_bearer(ENV_KEY))
    project_id = project.json()["id"]

    # Allowed: slug resolution, scores, live interactions, OTLP (empty body → not 401/403).
    assert (await client.get("/api/v1/projects", headers=_bearer(key))).status_code == 200
    scores = await client.post(
        f"/api/v1/projects/{project_id}/trace-scores",
        json={"scores": [{"trace_id": "a" * 32, "name": "thumbs", "value": 1, "source": "human"}]},
        headers=_bearer(key),
    )
    assert scores.status_code == 202, scores.text
    otlp = await client.post(
        "/v1/traces",
        content=b"",
        headers={**_bearer(key), "content-type": "application/x-protobuf"},
    )
    assert otlp.status_code not in (401, 403)

    # Denied: reading data, writing anything else, managing keys.
    for method, path in [
        ("GET", f"/api/v1/projects/{project_id}"),
        ("GET", f"/api/v1/projects/{project_id}/traces"),
        ("POST", "/api/v1/projects"),
        ("DELETE", f"/api/v1/projects/{project_id}"),
        ("GET", "/api/v1/api-keys"),
    ]:
        resp = await client.request(method, path, headers=_bearer(key), json={"name": "x"})
        assert resp.status_code == 403, (method, path, resp.text)
        assert "ingest" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_read_scope(client: AsyncClient) -> None:
    key = (await _create_key(client, "read"))["key"]
    project = await client.post("/api/v1/projects", json={"name": "p"}, headers=_bearer(ENV_KEY))
    project_id = project.json()["id"]

    assert (await client.get("/api/v1/projects", headers=_bearer(key))).status_code == 200
    assert (
        await client.get(f"/api/v1/projects/{project_id}", headers=_bearer(key))
    ).status_code == 200
    for method, path in [
        ("POST", "/api/v1/projects"),
        ("DELETE", f"/api/v1/projects/{project_id}"),
        ("POST", "/v1/traces"),
        ("GET", "/api/v1/api-keys"),
        ("POST", "/api/v1/api-keys"),
    ]:
        resp = await client.request(method, path, headers=_bearer(key), json={"name": "x"})
        assert resp.status_code == 403, (method, path)


@pytest.mark.asyncio
async def test_admin_table_key_can_manage_keys(client: AsyncClient) -> None:
    key = (await _create_key(client, "admin"))["key"]
    resp = await client.post(
        "/api/v1/api-keys", json={"name": "ci", "scope": "read"}, headers=_bearer(key)
    )
    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_revoked_key_rejected_at_once(client: AsyncClient) -> None:
    created = await _create_key(client, "read")
    assert (
        await client.get("/api/v1/projects", headers=_bearer(created["key"]))
    ).status_code == 200

    revoke = await client.delete(f"/api/v1/api-keys/{created['id']}", headers=_bearer(ENV_KEY))
    assert revoke.status_code == 204
    assert (
        await client.get("/api/v1/projects", headers=_bearer(created["key"]))
    ).status_code == 401
    listed = (await client.get("/api/v1/api-keys", headers=_bearer(ENV_KEY))).json()
    assert listed[0]["revoked_at"] is not None
    missing = await client.delete(
        "/api/v1/api-keys/00000000-0000-0000-0000-000000000000", headers=_bearer(ENV_KEY)
    )
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_last_used_recorded(client: AsyncClient) -> None:
    created = await _create_key(client, "read")
    assert created["last_used_at"] is None
    await client.get("/api/v1/projects", headers=_bearer(created["key"]))
    (row,) = (await client.get("/api/v1/api-keys", headers=_bearer(ENV_KEY))).json()
    assert row["last_used_at"] is not None


@pytest.mark.asyncio
async def test_ui_session_with_read_key_and_ingest_refused(client: AsyncClient) -> None:
    read = await _create_key(client, "read", "anna")
    ingest = await _create_key(client, "ingest")

    refused = await client.post("/api/v1/auth/session", json={"api_key": ingest["key"]})
    assert refused.status_code == 403

    ok = await client.post("/api/v1/auth/session", json={"api_key": read["key"]})
    assert ok.status_code == 204
    status = (await client.get("/api/v1/auth/status")).json()
    assert status == {
        "auth_required": True,
        "authenticated": True,
        "scope": "read",
        "key_name": "anna",
    }
    assert (await client.get("/api/v1/projects")).status_code == 200
    assert (await client.post("/api/v1/projects", json={"name": "x"})).status_code == 403

    # Revoking the key ends its UI session.
    await client.delete(f"/api/v1/api-keys/{read['id']}", headers=_bearer(ENV_KEY))
    assert (await client.get("/api/v1/projects")).status_code == 401


@pytest.mark.asyncio
async def test_create_refused_when_auth_off(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENGRADE_API_KEY")
    get_settings.cache_clear()
    resp = await client.post("/api/v1/api-keys", json={"name": "x", "scope": "read"})
    assert resp.status_code == 409
    assert "OPENGRADE_API_KEY" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_invalid_scope_rejected(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/api-keys", json={"name": "x", "scope": "owner"}, headers=_bearer(ENV_KEY)
    )
    assert resp.status_code == 422
