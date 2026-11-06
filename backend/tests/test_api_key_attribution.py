"""When auth is on, author/reviewer come from the API key name (body fields ignored)."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import select

from opengrade_server.api.deps import (
    get_dataset_repository,
    get_evaluator_repository,
    get_live_interaction_repository,
    get_metrics_set_repository,
    get_project_repository,
    get_trace_score_repository,
)
from opengrade_server.config import get_settings
from opengrade_server.evaluation import bootstrap_evaluators
from opengrade_server.evaluation.registry import clear_registry
from opengrade_server.infrastructure.db import (
    bootstrap_schema,
    dispose_db,
    get_session_factory,
    init_db,
)
from opengrade_server.infrastructure.models import TraceScoreModel
from opengrade_server.main import create_app
from support.fake_llm import ScriptedJudgeLlm
from support.repositories import (
    InMemoryEvaluatorRepository,
    InMemoryMetricsSetRepository,
    InMemoryTraceScoreRepository,
)
from test_api_live_interactions import (
    InMemoryDatasetRepository,
    InMemoryLiveRepository,
    InMemoryProjectRepository,
)

ENV_KEY = "env-admin-key-attribution-0123"
TID = "ab" * 16


def _bearer(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


@pytest.fixture
async def auth_client(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[AsyncClient]:
    db_path = tmp_path_factory.mktemp("attr") / "opengrade.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("OPENGRADE_API_KEY", ENV_KEY)
    monkeypatch.delenv("OPENGRADE_API_KEY_PREVIOUS", raising=False)
    get_settings.cache_clear()
    await dispose_db()
    init_db(get_settings())
    await bootstrap_schema()

    projects = InMemoryProjectRepository()
    live = InMemoryLiveRepository()
    metrics = InMemoryMetricsSetRepository()
    evaluators = InMemoryEvaluatorRepository()
    datasets = InMemoryDatasetRepository()

    app = create_app(mount_packaged_ui=False)
    clear_registry()
    bootstrap_evaluators(ScriptedJudgeLlm())
    app.dependency_overrides[get_project_repository] = lambda: projects
    app.dependency_overrides[get_live_interaction_repository] = lambda: live
    app.dependency_overrides[get_trace_score_repository] = lambda: InMemoryTraceScoreRepository()
    app.dependency_overrides[get_metrics_set_repository] = lambda: metrics
    app.dependency_overrides[get_evaluator_repository] = lambda: evaluators
    app.dependency_overrides[get_dataset_repository] = lambda: datasets

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c

    app.dependency_overrides.clear()
    clear_registry()
    await dispose_db()
    os.environ.pop("DATABASE_URL", None)
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_trace_score_author_from_key_name(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path_factory.mktemp("attr-db") / "opengrade.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("OPENGRADE_API_KEY", ENV_KEY)
    monkeypatch.delenv("OPENGRADE_API_KEY_PREVIOUS", raising=False)
    get_settings.cache_clear()
    await dispose_db()
    init_db(get_settings())
    await bootstrap_schema()
    app = create_app(mount_packaged_ui=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/api/v1/api-keys",
            json={"name": "alice-ingest", "scope": "ingest"},
            headers=_bearer(ENV_KEY),
        )
        assert created.status_code == 201, created.text
        key = created.json()["key"]

        project = await client.post(
            "/api/v1/projects",
            json={"name": "attr"},
            headers=_bearer(ENV_KEY),
        )
        project_id = project.json()["id"]

        resp = await client.post(
            f"/api/v1/projects/{project_id}/trace-scores",
            json={
                "scores": [
                    {
                        "trace_id": TID,
                        "name": "user_feedback",
                        "value": 1,
                        "source": "human",
                        "author": "spoofed-client",
                    }
                ]
            },
            headers=_bearer(key),
        )
        assert resp.status_code == 202, resp.text

        factory = get_session_factory()
        async with factory() as session:
            rows = (
                (
                    await session.execute(
                        select(TraceScoreModel).where(TraceScoreModel.trace_id == TID)
                    )
                )
                .scalars()
                .all()
            )
        assert len(rows) == 1
        assert rows[0].author == "alice-ingest"

    await dispose_db()
    os.environ.pop("DATABASE_URL", None)
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_live_review_reviewer_from_key_name(auth_client: AsyncClient) -> None:
    admin_key = await auth_client.post(
        "/api/v1/api-keys",
        json={"name": "bob-admin", "scope": "admin"},
        headers=_bearer(ENV_KEY),
    )
    assert admin_key.status_code == 201, admin_key.text
    key = admin_key.json()["key"]

    project = await auth_client.post(
        "/api/v1/projects",
        json={"name": "review-attr"},
        headers=_bearer(key),
    )
    project_id = project.json()["id"]

    ensure = await auth_client.post(
        f"/api/v1/projects/{project_id}/metrics-pack/ensure",
        headers=_bearer(key),
    )
    assert ensure.status_code == 200, ensure.text

    submit = await auth_client.post(
        f"/api/v1/projects/{project_id}/live-interactions",
        json={
            "question": "What is PTO?",
            "answer": "Paid time off",
            "documents": [{"id": "doc-1", "text": "PTO means paid time off"}],
        },
        headers=_bearer(key),
    )
    assert submit.status_code == 202, submit.text
    interaction_id = submit.json()["id"]

    scored = await auth_client.post(
        f"/api/v1/live-interactions/{interaction_id}/rescore",
        headers=_bearer(key),
    )
    assert scored.status_code == 200, scored.text
    scores = scored.json()["scores"]
    assert scores, scored.text
    score_id = scores[0]["id"]

    review = await auth_client.post(
        f"/api/v1/live-interaction-scores/{score_id}/review",
        json={"verdict": "agree", "reviewer": "spoofed-reviewer"},
        headers=_bearer(key),
    )
    assert review.status_code == 200, review.text
    assert review.json()["reviewer"] == "bob-admin"
