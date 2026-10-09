from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from aiobs_server.api.errors import register_exception_handlers
from aiobs_server.api.routes import api_router
from aiobs_server.api.schemas import HealthResponse
from aiobs_server.config import get_settings
from aiobs_server.evaluation import bootstrap_evaluators
from aiobs_server.evaluation.registry import clear_registry
from aiobs_server.infrastructure.db import bootstrap_schema, dispose_db, init_db
from aiobs_server.infrastructure.llm import LiteLlmClient
from aiobs_server.infrastructure.repositories import SqlJudgeClaimCache
from aiobs_server.ui import mount_ui


def _ensure_evaluators_registered() -> None:
    settings = get_settings()
    clear_registry()
    bootstrap_evaluators(
        LiteLlmClient(settings),
        default_model=settings.llm_model,
        claim_cache=SqlJudgeClaimCache(),
    )


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    init_db()
    await bootstrap_schema()
    _ensure_evaluators_registered()
    yield
    await dispose_db()


def create_app(*, mount_packaged_ui: bool = True) -> FastAPI:
    _ensure_evaluators_registered()
    app = FastAPI(
        title="AI Evaluation & Observability Platform",
        version="0.1.0",
        lifespan=lifespan,
    )
    register_exception_handlers(app)
    app.include_router(api_router)

    @app.get("/health", response_model=HealthResponse, tags=["health"])
    async def health() -> HealthResponse:
        return HealthResponse(status="ok")

    if mount_packaged_ui:
        mount_ui(app)

    return app


app = create_app()
