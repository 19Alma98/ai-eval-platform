"""Health readiness, metrics, and request ID middleware."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, patch

import pytest
from httpx2 import ASGITransport, AsyncClient

from opengrade_server.config import get_settings
from opengrade_server.infrastructure.db import bootstrap_schema, dispose_db, init_db
from opengrade_server.main import create_app


@pytest.fixture
async def obs_client(tmp_path_factory: pytest.TempPathFactory) -> AsyncIterator[AsyncClient]:
    db_path = tmp_path_factory.mktemp("obs") / "opengrade.db"
    previous_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"
    get_settings.cache_clear()
    await dispose_db()
    init_db(get_settings())
    await bootstrap_schema()

    app = create_app(mount_packaged_ui=False)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    await dispose_db()
    if previous_url is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = previous_url
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_ready_ok_when_db_up(obs_client: AsyncClient) -> None:
    response = await obs_client.get("/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_ready_503_when_db_down(obs_client: AsyncClient) -> None:
    with patch(
        "opengrade_server.main.check_db_ready",
        new_callable=AsyncMock,
        return_value=False,
    ):
        response = await obs_client.get("/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"


@pytest.mark.asyncio
async def test_request_id_generated_and_echoed(obs_client: AsyncClient) -> None:
    response = await obs_client.get("/health")
    assert response.status_code == 200
    rid = response.headers.get("x-request-id")
    assert rid
    assert len(rid) >= 8


@pytest.mark.asyncio
async def test_request_id_propagated_from_client(obs_client: AsyncClient) -> None:
    response = await obs_client.get("/health", headers={"X-Request-ID": "client-req-1"})
    assert response.headers.get("x-request-id") == "client-req-1"
