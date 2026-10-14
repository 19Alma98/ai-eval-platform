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
    """What a ``@aiobs.trace(metrics=...)`` call recorded, for its production metrics.

    ``span`` is the call's own span: only ``set_input`` on that span sets ``input``
    (a nested call rewriting its own input must not change it); documents from nested
    retrieval stages on the same thread do bubble up. ContextVars are not copied into
    threads the traced function starts, so ``set_retrieval_documents`` there is a no-op
    for this capture.
    """

    span: object = None
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


def record_input(value: object, span: object) -> None:
    """Record ``value`` as the production input when ``span`` owns the open capture."""
    capture = PRODUCTION_CAPTURE.get()
    if capture is not None and capture.span is span:
        capture.input = value
        capture.has_input = True
