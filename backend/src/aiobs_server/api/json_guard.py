"""Reject JSON request bodies that carry NaN or Infinity.

Python's json module accepts these non-standard tokens, so a non-finite float would
either break the 422 response that echoes it back or be stored and break every later
response that serializes it. Checking the raw body covers every endpoint, including
free-form ``Any`` fields that pydantic's ``allow_inf_nan`` cannot reach.

Also enforces ``max_body_bytes`` while buffering so route-level size checks are not
the first memory bound for JSON requests.
"""

from __future__ import annotations

import json
import math

from fastapi import status
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class _NonFiniteNumberError(ValueError):
    pass


def _reject_constant(token: str) -> float:
    raise _NonFiniteNumberError(token)


def _finite_float(token: str) -> float:
    value = float(token)
    if not math.isfinite(value):  # e.g. 1e999 overflows to inf
        raise _NonFiniteNumberError(token)
    return value


def find_non_finite_number(body: bytes) -> str | None:
    """Return the first NaN/Infinity token in a JSON body, or None."""
    try:
        json.loads(body, parse_constant=_reject_constant, parse_float=_finite_float)
    except _NonFiniteNumberError as exc:
        return str(exc)
    except ValueError:  # malformed JSON or encoding: left to FastAPI's json_invalid
        return None
    return None


def _is_json(scope: Scope) -> bool:
    for name, value in scope["headers"]:
        if name == b"content-type":
            media_type: bytes = value.split(b";", 1)[0].strip().lower()
            return media_type == b"application/json" or (
                media_type.startswith(b"application/") and media_type.endswith(b"+json")
            )
    return False


def _content_length(scope: Scope) -> int | None:
    for name, value in scope["headers"]:
        if name == b"content-length":
            try:
                return int(value)
            except ValueError:
                return None
    return None


def _too_large_response() -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
        content={"detail": "Request body too large"},
    )


async def _drain(receive: Receive) -> None:
    while True:
        message = await receive()
        if message["type"] != "http.request" or not message.get("more_body", False):
            return


class RejectNonFiniteJsonMiddleware:
    def __init__(self, app: ASGIApp, *, max_body_bytes: int = 4 * 1024 * 1024) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not _is_json(scope):
            await self.app(scope, receive, send)
            return

        declared = _content_length(scope)
        if declared is not None and declared > self.max_body_bytes:
            await _too_large_response()(scope, receive, send)
            return

        messages: list[Message] = []
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] != "http.request":
                messages.append(message)
                break
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > self.max_body_bytes:
                if message.get("more_body", False):
                    await _drain(receive)
                await _too_large_response()(scope, receive, send)
                return
            body += chunk
            messages.append(message)
            if not message.get("more_body", False):
                break

        token = find_non_finite_number(bytes(body)) if body else None
        if token is not None:
            response = JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                content={
                    "detail": [
                        {
                            "type": "finite_number",
                            "loc": ["body"],
                            "msg": "Input should be a finite number",
                            "input": token,
                        }
                    ]
                },
            )
            await response(scope, receive, send)
            return

        replay = iter(messages)

        async def replay_receive() -> Message:
            return next(replay, None) or await receive()

        await self.app(scope, replay_receive, send)
