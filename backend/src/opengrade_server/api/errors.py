from __future__ import annotations

import logging
import math
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from opengrade_server.application.app_configs import (
    AppConfigAliasNotFoundError,
    AppConfigNotFoundError,
)
from opengrade_server.application.compare import InvalidCompareSelectionError
from opengrade_server.application.compare_items import AmbiguousEvaluatorError, DatasetMismatchError
from opengrade_server.application.datasets import DatasetConflictError, DatasetNotFoundError
from opengrade_server.application.evaluate import (
    EmptyEvaluatorListError,
    EvaluationRunNotFoundError,
)
from opengrade_server.application.evaluators import (
    EvaluatorConflictError,
    EvaluatorNotFoundError,
    UnknownEvaluatorKindError,
)
from opengrade_server.application.experiments import ExperimentNotFoundError
from opengrade_server.application.live_interactions import (
    LiveInteractionNotFoundError,
    LiveScoreNotFoundError,
)
from opengrade_server.application.metrics_packs import (
    MetricsPackNotFoundError,
    MetricsPackValidationError,
)
from opengrade_server.application.metrics_sets import (
    MetricsSetConflictError,
    MetricsSetEntryNotFoundError,
    MetricsSetNotFoundError,
    MetricsSetProtectedError,
    MetricsSetReferencedError,
    MetricsSetValidationError,
)
from opengrade_server.application.projects import ProjectNotFoundError, ProjectSlugConflictError
from opengrade_server.application.release_check import MissingBaselineError
from opengrade_server.application.traces import ProjectMissingError, TraceNotFoundError
from opengrade_server.regression.policy import InvalidPolicyError

logger = logging.getLogger(__name__)

ExceptionHandler = Callable[[Request, Exception], Awaitable[JSONResponse]]

_NOT_FOUND: tuple[type[Exception], ...] = (
    ProjectNotFoundError,
    ProjectMissingError,
    DatasetNotFoundError,
    ExperimentNotFoundError,
    EvaluatorNotFoundError,
    EvaluationRunNotFoundError,
    AppConfigNotFoundError,
    AppConfigAliasNotFoundError,
    MetricsPackNotFoundError,
    MetricsSetNotFoundError,
    MetricsSetEntryNotFoundError,
    TraceNotFoundError,
    LiveInteractionNotFoundError,
    LiveScoreNotFoundError,
)

_CONFLICT: tuple[type[Exception], ...] = (
    ProjectSlugConflictError,
    DatasetConflictError,
    EvaluatorConflictError,
    MetricsSetConflictError,
    MetricsSetReferencedError,
    MetricsSetProtectedError,
)

INTEGRITY_CONFLICT_DETAIL = "Resource conflict"

_BAD_REQUEST: tuple[type[Exception], ...] = (
    InvalidPolicyError,
    MissingBaselineError,
    InvalidCompareSelectionError,
    UnknownEvaluatorKindError,
    EmptyEvaluatorListError,
    MetricsSetValidationError,
    MetricsPackValidationError,
    DatasetMismatchError,
    AmbiguousEvaluatorError,
)


def _detail_response(status_code: int, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"detail": str(exc)})


def _handler_for(status_code: int) -> ExceptionHandler:
    async def handler(_request: Request, exc: Exception) -> JSONResponse:
        return _detail_response(status_code, exc)

    return handler


def _json_safe(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


async def request_validation_error(_request: Request, exc: Exception) -> JSONResponse:
    # FastAPI's default handler echoes each invalid input back, and a NaN/Infinity
    # input (e.g. from a query string) cannot be serialized: that would be a 500.
    assert isinstance(exc, RequestValidationError)
    errors = _json_safe(jsonable_encoder(exc.errors()))
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content={"detail": errors}
    )


async def integrity_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    logger.warning("Database integrity conflict", exc_info=exc)
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"detail": INTEGRITY_CONFLICT_DETAIL},
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, request_validation_error)
    not_found = _handler_for(status.HTTP_404_NOT_FOUND)
    conflict = _handler_for(status.HTTP_409_CONFLICT)
    bad_request = _handler_for(status.HTTP_400_BAD_REQUEST)
    for exc_type in _NOT_FOUND:
        app.add_exception_handler(exc_type, not_found)
    for exc_type in _CONFLICT:
        app.add_exception_handler(exc_type, conflict)
    app.add_exception_handler(IntegrityError, integrity_error_handler)
    for exc_type in _BAD_REQUEST:
        app.add_exception_handler(exc_type, bad_request)
