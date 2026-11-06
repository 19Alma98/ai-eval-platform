"""LLM settings overlay + API (admin-only); API key stays in ``.env``."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from httpx2 import ASGITransport, AsyncClient

from opengrade_server.application.llm_settings import (
    EffectiveLlmSettings,
    llm_settings_store,
)
from opengrade_server.config import Settings, get_settings
from opengrade_server.infrastructure.db import bootstrap_schema, dispose_db, init_db
from opengrade_server.main import create_app

ENV_KEY = "env-admin-key-llm-settings"


def _bearer(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


@pytest.fixture
async def client(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[AsyncClient]:
    root = tmp_path_factory.mktemp("llm_settings")
    db_path = root / "opengrade.db"
    monkeypatch.chdir(root)
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("OPENGRADE_API_KEY", ENV_KEY)
    monkeypatch.setenv("LLM_MODEL", "env/model")
    monkeypatch.setenv("LLM_API_KEY", "env-secret")
    monkeypatch.delenv("OPENGRADE_API_KEY_PREVIOUS", raising=False)
    monkeypatch.delenv("LLM_API_BASE", raising=False)
    get_settings.cache_clear()
    llm_settings_store.clear_cache()
    await dispose_db()
    init_db(get_settings())
    await bootstrap_schema()
    await llm_settings_store.get_effective()
    app = create_app(mount_packaged_ui=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await dispose_db()
    llm_settings_store.clear_cache()
    os.environ.pop("DATABASE_URL", None)
    get_settings.cache_clear()


def test_merge_overlay_prefers_db_fields() -> None:
    base = Settings(llm_model="env/m", llm_api_key="k", llm_temperature=0.0, llm_seed=1)
    from opengrade_server.infrastructure.models import SystemLlmSettingsModel

    row = SystemLlmSettingsModel(id=1, model="db/m", temperature=0.5, seed=None)
    # seed=None on row means "no overlay" for seed — but attribute is None.
    # Overlay merge only applies non-None columns.
    merged = llm_settings_store._merge(base, row)
    assert merged.model == "db/m"
    assert merged.sources["model"] == "db"
    assert merged.temperature == 0.5
    assert merged.sources["temperature"] == "db"
    assert merged.seed == 1
    assert merged.sources["seed"] == "env"
    assert merged.api_key == "k"
    assert merged.api_key_set is True


def test_from_env_snapshot() -> None:
    eff = EffectiveLlmSettings.from_env(Settings(llm_model="m", llm_api_key=None))
    assert eff.model == "m"
    assert eff.api_key_set is False
    assert all(src == "env" for src in eff.sources.values())


async def test_get_masks_api_key(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/settings/llm", headers=_bearer(ENV_KEY))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["model"] == "env/model"
    assert body["api_key_set"] is True
    assert "api_key" not in body
    assert body["sources"]["model"] == "env"


async def test_put_overlay_and_reset(client: AsyncClient) -> None:
    put = await client.put(
        "/api/v1/settings/llm",
        json={"model": "ui/model", "temperature": 0.2},
        headers=_bearer(ENV_KEY),
    )
    assert put.status_code == 200, put.text
    body = put.json()
    assert body["model"] == "ui/model"
    assert body["sources"]["model"] == "db"
    assert body["temperature"] == 0.2
    assert body["api_key_set"] is True

    got = await client.get("/api/v1/settings/llm", headers=_bearer(ENV_KEY))
    assert got.json()["model"] == "ui/model"

    reset = await client.post("/api/v1/settings/llm/reset", headers=_bearer(ENV_KEY))
    assert reset.status_code == 200, reset.text
    assert reset.json()["model"] == "env/model"
    assert reset.json()["sources"]["model"] == "env"


async def test_put_api_key_writes_dotenv(client: AsyncClient) -> None:
    # cwd is already the fixture temp dir
    put = await client.put(
        "/api/v1/settings/llm",
        json={"api_key": "from-ui"},
        headers=_bearer(ENV_KEY),
    )
    assert put.status_code == 200, put.text
    assert put.json()["api_key_set"] is True
    env_text = Path.cwd().joinpath(".env").read_text(encoding="utf-8")
    assert "LLM_API_KEY=from-ui" in env_text or 'LLM_API_KEY="from-ui"' in env_text
    assert os.environ.get("LLM_API_KEY") == "from-ui"

    clear = await client.put(
        "/api/v1/settings/llm",
        json={"api_key": None},
        headers=_bearer(ENV_KEY),
    )
    assert clear.status_code == 200, clear.text
    assert clear.json()["api_key_set"] is False
    assert "LLM_API_KEY" not in Path.cwd().joinpath(".env").read_text(encoding="utf-8")
    assert "LLM_API_KEY" not in os.environ


async def test_read_scope_forbidden(client: AsyncClient) -> None:
    created = await client.post(
        "/api/v1/api-keys",
        json={"name": "reader", "scope": "read"},
        headers=_bearer(ENV_KEY),
    )
    assert created.status_code == 201, created.text
    key = created.json()["key"]
    resp = await client.get("/api/v1/settings/llm", headers=_bearer(key))
    assert resp.status_code == 403


async def test_clear_overlay_field_with_null(client: AsyncClient) -> None:
    await client.put(
        "/api/v1/settings/llm",
        json={"model": "ui/model"},
        headers=_bearer(ENV_KEY),
    )
    cleared = await client.put(
        "/api/v1/settings/llm",
        json={"model": None},
        headers=_bearer(ENV_KEY),
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["model"] == "env/model"
    assert cleared.json()["sources"]["model"] == "env"


async def test_client_uses_overlay_without_restart(client: AsyncClient) -> None:
    from opengrade_server.application.llm_settings import get_effective_llm_settings_sync
    from opengrade_server.infrastructure.llm import LiteLlmClient

    await client.put(
        "/api/v1/settings/llm",
        json={"model": "runtime/model", "api_base": "http://example.test"},
        headers=_bearer(ENV_KEY),
    )
    cfg = get_effective_llm_settings_sync()
    assert cfg.model == "runtime/model"
    assert cfg.api_base == "http://example.test"
    assert LiteLlmClient()._resolve().model == "runtime/model"
