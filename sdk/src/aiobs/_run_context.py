"""Active experiment item run, so ``set_output`` & co. feed it without tracing."""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Protocol


class _Recorder(Protocol):
    def _capture_output(self, value: object) -> None: ...

    def _capture_documents(self, documents: list[dict[str, Any]]) -> None: ...


ACTIVE_RUN: ContextVar[_Recorder | None] = ContextVar("aiobs_active_run", default=None)


def record_output(value: object) -> None:
    run = ACTIVE_RUN.get()
    if run is not None:
        run._capture_output(value)


def record_documents(documents: list[dict[str, Any]]) -> None:
    run = ACTIVE_RUN.get()
    if run is not None:
        run._capture_documents(documents)
