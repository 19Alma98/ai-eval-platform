from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from opengrade_server import __version__
from opengrade_server.api.errors import register_exception_handlers
from opengrade_server.api.json_guard import RejectNonFiniteJsonMiddleware
from opengrade_server.api.routes import api_router
from opengrade_server.api.schemas import HealthResponse
from opengrade_server.config import get_settings
from opengrade_server.evaluation import bootstrap_evaluators
from opengrade_server.evaluation.registry import clear_registry
from opengrade_server.infrastructure.db import bootstrap_schema, dispose_db, init_db
from opengrade_server.infrastructure.llm import LiteLlmClient
from opengrade_server.infrastructure.repositories import SqlJudgeClaimCache
from opengrade_server.ui import mount_ui


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
    from opengrade_server.application.scoring_recovery import recover_scoring_after_restart

    init_db()
    await bootstrap_schema()
    _ensure_evaluators_registered()
    await recover_scoring_after_restart()
    yield
    await dispose_db()


def create_app(*, mount_packaged_ui: bool = True) -> FastAPI:
    _ensure_evaluators_registered()
    app = FastAPI(
        title="AI Evaluation & Observability Platform",
        version=__version__,
        lifespan=lifespan,
    )
    register_exception_handlers(app)
    app.add_middleware(
        RejectNonFiniteJsonMiddleware,
        max_body_bytes=get_settings().json_max_body_bytes,
    )
    app.include_router(api_router)

    @app.get("/health", response_model=HealthResponse, tags=["health"])
    async def health() -> HealthResponse:
        return HealthResponse(status="ok")

    if mount_packaged_ui:
        mount_ui(app)

    return app


app = create_app()
