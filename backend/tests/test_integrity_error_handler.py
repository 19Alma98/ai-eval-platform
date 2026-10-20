from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy.exc import IntegrityError

from opengrade_server.api.errors import INTEGRITY_CONFLICT_DETAIL, register_exception_handlers


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    async def boom() -> None:
        raise IntegrityError(
            "INSERT INTO secret_table (content) VALUES ($1)",
            {"content": "user-private-payload"},
            Exception("UNIQUE constraint failed"),
        )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_integrity_error_returns_generic_detail(client: AsyncClient) -> None:
    resp = await client.get("/boom")
    assert resp.status_code == 409
    assert resp.json() == {"detail": INTEGRITY_CONFLICT_DETAIL}
    body = resp.text
    assert "INSERT" not in body
    assert "secret_table" not in body
    assert "user-private-payload" not in body
    assert "$1" not in body
