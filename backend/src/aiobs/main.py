from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from aiobs.api.routes import api_router
from aiobs.api.schemas import HealthResponse
from aiobs.config import get_settings
from aiobs.evaluation import bootstrap_evaluators
from aiobs.evaluation.registry import clear_registry
from aiobs.infrastructure.db import dispose_db, init_db
from aiobs.infrastructure.llm import LiteLlmClient
from aiobs.infrastructure.repositories import SqlJudgeClaimCache


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
    _ensure_evaluators_registered()
    yield
    await dispose_db()


def create_app() -> FastAPI:
    _ensure_evaluators_registered()
    app = FastAPI(
        title="AI Evaluation & Observability Platform",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.include_router(api_router)

    @app.get("/health", response_model=HealthResponse, tags=["health"])
    async def health() -> HealthResponse:
        return HealthResponse(status="ok")

    return app


app = create_app()
