"""Per-call capture for experiment runs and production metrics (output, input, documents)."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Protocol


class _Recorder(Protocol):
    def _capture_output(self, value: object) -> None: ...

    def _capture_documents(self, documents: list[dict[str, Any]]) -> None: ...


ACTIVE_RUN: ContextVar[_Recorder | None] = ContextVar("aiobs_active_run", default=None)


@dataclass
class ProductionCapture:
    """What a ``@aiobs.trace(metrics=...)`` call recorded, for its production metrics."""

    input: object = None
    has_input: bool = False
    documents: list[dict[str, Any]] | None = None


PRODUCTION_CAPTURE: ContextVar[ProductionCapture | None] = ContextVar(
    "aiobs_production_capture", default=None
)


def record_output(value: object) -> None:
    run = ACTIVE_RUN.get()
    if run is not None:
        run._capture_output(value)


def record_documents(documents: list[dict[str, Any]]) -> None:
    run = ACTIVE_RUN.get()
    if run is not None:
        run._capture_documents(documents)
    capture = PRODUCTION_CAPTURE.get()
    if capture is not None:
        capture.documents = documents  # last retrieval stage wins, as in experiments


def record_input(value: object) -> None:
    capture = PRODUCTION_CAPTURE.get()
    if capture is not None:
        capture.input = value
        capture.has_input = True
