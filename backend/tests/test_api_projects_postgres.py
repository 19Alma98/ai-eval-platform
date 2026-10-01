from __future__ import annotations

import os
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine

from aiobs.infrastructure.db import dispose_db, init_db
from aiobs.infrastructure.models import Base
from aiobs.main import create_app

DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    os.getenv("DATABASE_URL", "postgresql+asyncpg://aiobs:aiobs@localhost:5434/aiobs"),
)

pytestmark = pytest.mark.integration


@pytest.fixture
async def client() -> AsyncClient:
    engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
    except Exception as exc:  # noqa: BLE001
        await engine.dispose()
        pytest.skip(f"PostgreSQL not available for integration tests: {exc}")

    await engine.dispose()

    os.environ["DATABASE_URL"] = DATABASE_URL
    from aiobs.config import get_settings

    get_settings.cache_clear()
    await dispose_db()
    init_db(get_settings())

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    await dispose_db()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_health_with_postgres(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_create_project_persisted(client: AsyncClient) -> None:
    create = await client.post("/api/v1/projects", json={"name": "Persisted"})
    assert create.status_code == 201
    project_id = create.json()["id"]

    got = await client.get(f"/api/v1/projects/{project_id}")
    assert got.status_code == 200
    assert got.json()["name"] == "Persisted"
    assert uuid.UUID(got.json()["id"]) == uuid.UUID(project_id)
