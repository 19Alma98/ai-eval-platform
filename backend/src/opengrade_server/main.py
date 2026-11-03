import asyncio
import inspect
from collections.abc import AsyncIterator, MutableMapping
from contextlib import asynccontextmanager, suppress
from typing import Any

from fastapi import FastAPI, Response, status
from fastapi.responses import JSONResponse

from opengrade_server import __version__
from opengrade_server.api.auth import ApiKeyAuthMiddleware
from opengrade_server.api.errors import register_exception_handlers
from opengrade_server.api.json_guard import RejectNonFiniteJsonMiddleware
from opengrade_server.api.request_id import RequestIdMiddleware, configure_request_id_logging
from opengrade_server.api.routes import api_router
from opengrade_server.api.schemas import HealthResponse
from opengrade_server.config import get_settings
from opengrade_server.evaluation import bootstrap_evaluators
from opengrade_server.evaluation.registry import clear_registry
from opengrade_server.infrastructure.db import (
    bootstrap_schema,
    check_db_ready,
    dispose_db,
    init_db,
)
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
    from opengrade_server.application.alerts import run_alert_loop
    from opengrade_server.application.retention import run_retention_loop
    from opengrade_server.application.scoring_recovery import recover_scoring_after_restart

    init_db()
    await bootstrap_schema()
    _ensure_evaluators_registered()
    await recover_scoring_after_restart()
    settings = get_settings()
    alert_loop = (
        asyncio.create_task(run_alert_loop(settings.alerts_interval_seconds), name="alert-loop")
        if settings.alerts_enabled
        else None
    )
    retention_loop = (
        asyncio.create_task(
            run_retention_loop(settings.retention_interval_hours), name="retention-loop"
        )
        if settings.retention_interval_hours > 0
        else None
    )
    yield
    for task in (alert_loop, retention_loop):
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
    await dispose_db()


OTLP_TRACES_PATH = "/v1/traces"


def _is_otlp_ingest(scope: MutableMapping[str, Any]) -> bool:
    return bool(scope.get("path") == OTLP_TRACES_PATH)


def _telemetry_kwargs(*, self_telemetry: bool) -> dict[str, Any]:
    """FastAPI native OpenTelemetry settings (FastAPI >= 0.142; older versions have none).

    OTLP ingest requests are never traced: when the server shares a tracer provider with
    an exporter pointing back at itself, each export would create spans that are exported
    again, a feedback loop. ``self_telemetry=False`` turns the server's own telemetry
    off: the embedded server of ``opengrade evaluate`` runs in the same process as the
    SDK, whose global tracer provider would otherwise record every API call of the run
    as a trace of the project under test.
    """
    if "telemetry" not in inspect.signature(FastAPI.__init__).parameters:
        return {}
    if not self_telemetry:
        return {
            "telemetry": {
                "tracing": False,
                "operation_spans": False,
                "metrics": False,
                "logs": False,
                "auto_configure": False,
            }
        }
    return {"telemetry": {"exclude": _is_otlp_ingest}}


def create_app(*, mount_packaged_ui: bool = True, self_telemetry: bool = True) -> FastAPI:
    configure_request_id_logging()
    _ensure_evaluators_registered()
    app = FastAPI(
        title="OpenGrade",
        version=__version__,
        lifespan=lifespan,
        **_telemetry_kwargs(self_telemetry=self_telemetry),
    )
    register_exception_handlers(app)
    # Last added = outermost: request ID > API key auth > JSON guard, so a request
    # without a valid key is rejected before its body is read.
    app.add_middleware(
        RejectNonFiniteJsonMiddleware,
        max_body_bytes=get_settings().json_max_body_bytes,
    )
    app.add_middleware(ApiKeyAuthMiddleware)
    app.add_middleware(RequestIdMiddleware)
    app.include_router(api_router)

    @app.get("/health", response_model=HealthResponse, tags=["health"])
    async def health() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.get("/ready", tags=["health"])
    async def ready() -> Response:
        if await check_db_ready():
            return JSONResponse({"status": "ok"})
        return JSONResponse(
            {"status": "not_ready"},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    if mount_packaged_ui:
        mount_ui(app)

    return app


app = create_app()
