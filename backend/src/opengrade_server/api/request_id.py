"""Propagate or generate ``X-Request-ID`` for correlation."""

from __future__ import annotations

import contextvars
import logging
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = b"x-request-id"
_request_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)


def get_request_id() -> str | None:
    return _request_id_ctx.get()


class RequestIdLogFilter(logging.Filter):
    """Attach ``request_id`` to log records from the context var."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id() or "-"
        return True


_logging_configured = False


def configure_request_id_logging() -> None:
    """Ensure root handlers include ``%(request_id)s`` when formatting."""
    global _logging_configured
    if _logging_configured:
        return
    _logging_configured = True
    root = logging.getLogger()
    filt = RequestIdLogFilter()
    for handler in root.handlers:
        handler.addFilter(filt)
        if handler.formatter is None:
            handler.setFormatter(
                logging.Formatter("%(levelname)s [%(request_id)s] %(name)s: %(message)s")
            )


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming: str | None = None
        for name, value in scope.get("headers") or []:
            if name == REQUEST_ID_HEADER:
                incoming = value.decode("latin-1").strip() or None
                break
        request_id = incoming or str(uuid.uuid4())
        token = _request_id_ctx.set(request_id)

        async def send_with_header(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                headers.append((REQUEST_ID_HEADER, request_id.encode("latin-1")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_header)
        finally:
            _request_id_ctx.reset(token)
