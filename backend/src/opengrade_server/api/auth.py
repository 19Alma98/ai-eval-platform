"""API key authentication (phase 1: one admin key from ``OPENGRADE_API_KEY``).

When no key is configured the server stays open, as on localhost / a trusted network.
When a key is set, every ``/api/*`` and OTLP ``/v1/traces`` request needs either
``Authorization: Bearer <key>`` (SDK, CLI, CI, OTel exporters) or the UI session cookie
issued by ``POST /api/v1/auth/session``. ``/health``, ``/ready`` and the static UI
stay public; the UI asks for the key when the API answers ``401``.

The session cookie never holds the key: it is ``<expiry>.<HMAC(key, expiry)>``, so
rotating the key also ends every UI session signed with the old one.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time

from starlette.types import ASGIApp, Receive, Scope, Send

from opengrade_server.config import Settings, get_settings

SESSION_COOKIE = "opengrade_session"
OTLP_TRACES_PATH = "/v1/traces"
AUTH_STATUS_PATH = "/api/v1/auth/status"
AUTH_SESSION_PATH = "/api/v1/auth/session"
_SESSION_CONTEXT = b"opengrade-ui-session"


def _is_protected(path: str) -> bool:
    if path in (AUTH_STATUS_PATH, AUTH_SESSION_PATH):
        return False
    return path.startswith("/api/") or path.rstrip("/") == OTLP_TRACES_PATH


def key_matches(candidate: str, settings: Settings) -> bool:
    """Constant-time check of ``candidate`` against the current and previous key."""
    raw = candidate.strip().encode()
    matched = False
    for key in settings.accepted_api_keys():
        # No early exit: the time taken does not reveal which key matched.
        matched |= hmac.compare_digest(raw, key.encode())
    return matched and bool(raw)


def _sign(key: str, expires_at: int) -> str:
    message = _SESSION_CONTEXT + b"." + str(expires_at).encode()
    return hmac.new(key.encode(), message, hashlib.sha256).hexdigest()


def issue_session_token(settings: Settings, *, now: float | None = None) -> tuple[str, int]:
    """Session cookie value signed with the current key, and its lifetime in seconds."""
    key = settings.accepted_api_keys()[0]
    max_age = int(settings.ui_session_hours * 3600)
    expires_at = int(now if now is not None else time.time()) + max_age
    return f"{expires_at}.{_sign(key, expires_at)}", max_age


def session_token_valid(token: str, settings: Settings, *, now: float | None = None) -> bool:
    expires_raw, _, signature = token.partition(".")
    if not expires_raw.isdigit() or not signature:
        return False
    expires_at = int(expires_raw)
    if expires_at <= (now if now is not None else time.time()):
        return False
    matched = False
    for key in settings.accepted_api_keys():
        matched |= hmac.compare_digest(signature, _sign(key, expires_at))
    return matched


def _cookie_value(cookie_header: str, name: str) -> str | None:
    for part in cookie_header.split(";"):
        cookie_name, sep, value = part.strip().partition("=")
        if sep and cookie_name == name:
            return value
    return None


def headers_authenticated(headers: dict[str, str], settings: Settings) -> bool:
    """True when the request carries a valid bearer key or UI session cookie.

    ``headers`` has lower-case names.
    """
    authorization = headers.get("authorization", "")
    scheme, _, credentials = authorization.partition(" ")
    if scheme.lower() == "bearer" and credentials.strip():
        return key_matches(credentials, settings)
    token = _cookie_value(headers.get("cookie", ""), SESSION_COOKIE)
    return token is not None and session_token_valid(token, settings)


class ApiKeyAuthMiddleware:
    """Reject unauthenticated ``/api`` and OTLP requests with ``401`` when a key is set."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not _is_protected(scope.get("path", "")):
            await self.app(scope, receive, send)
            return
        settings = get_settings()
        if not settings.accepted_api_keys():
            await self.app(scope, receive, send)
            return
        headers = {
            name.decode("latin-1").lower(): value.decode("latin-1")
            for name, value in scope.get("headers") or []
        }
        if headers_authenticated(headers, settings):
            await self.app(scope, receive, send)
            return
        body = json.dumps(
            {"detail": "missing or invalid API key (Authorization: Bearer <OPENGRADE_API_KEY>)"}
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"www-authenticate", b'Bearer realm="opengrade"'),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
