from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from aiobs_server.application.app_configs import AppConfigAliasNotFoundError, AppConfigNotFoundError
from aiobs_server.application.compare import InvalidCompareSelectionError
from aiobs_server.application.compare_items import AmbiguousEvaluatorError, DatasetMismatchError
from aiobs_server.application.datasets import DatasetConflictError, DatasetNotFoundError
from aiobs_server.application.evaluate import EmptyEvaluatorListError, EvaluationRunNotFoundError
from aiobs_server.application.evaluators import (
    EvaluatorConflictError,
    EvaluatorNotFoundError,
    UnknownEvaluatorKindError,
)
from aiobs_server.application.experiments import ExperimentNotFoundError
from aiobs_server.application.live_interactions import (
    LiveInteractionNotFoundError,
    LiveScoreNotFoundError,
)
from aiobs_server.application.metrics_packs import (
    MetricsPackNotFoundError,
    MetricsPackValidationError,
)
from aiobs_server.application.metrics_sets import (
    MetricsSetConflictError,
    MetricsSetEntryNotFoundError,
    MetricsSetNotFoundError,
    MetricsSetProtectedError,
    MetricsSetReferencedError,
    MetricsSetValidationError,
)
from aiobs_server.application.projects import ProjectNotFoundError, ProjectSlugConflictError
from aiobs_server.application.release_check import MissingBaselineError
from aiobs_server.application.traces import ProjectMissingError, TraceNotFoundError
from aiobs_server.regression.policy import InvalidPolicyError

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
    IntegrityError,
)

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


def register_exception_handlers(app: FastAPI) -> None:
    not_found = _handler_for(status.HTTP_404_NOT_FOUND)
    conflict = _handler_for(status.HTTP_409_CONFLICT)
    bad_request = _handler_for(status.HTTP_400_BAD_REQUEST)
    for exc_type in _NOT_FOUND:
        app.add_exception_handler(exc_type, not_found)
    for exc_type in _CONFLICT:
        app.add_exception_handler(exc_type, conflict)
    for exc_type in _BAD_REQUEST:
        app.add_exception_handler(exc_type, bad_request)
