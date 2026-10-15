"""Public SDK exception types (kept separate from ``_http`` for fast imports)."""

from __future__ import annotations

from typing import Any


class OpengradeError(Exception):
    """Base error for opengrade SDK failures."""


class OpengradeAPIError(OpengradeError):
    """Raised when the platform API returns a non-2xx response."""

    def __init__(self, status: int, body: str, *, detail: Any = None) -> None:
        self.status = status
        self.body = body
        self.detail = detail
        super().__init__(f"HTTP {status}: {body}")


class OpengradeConnectionError(OpengradeError):
    """Raised when the platform cannot be reached (DNS, connect, timeout, …)."""

    def __init__(self, message: str, *, cause: BaseException | None = None) -> None:
        self.__cause__ = cause
        super().__init__(message)
