"""API key authentication and scopes.

Auth is on when ``OPENGRADE_API_KEY`` is set; without it the server stays open, as on
localhost / a trusted network, and no key is checked. With it, every ``/api/*`` and OTLP
``/v1/traces`` request needs either ``Authorization: Bearer <key>`` (SDK, CLI, CI, OTel
exporters) or the UI session cookie issued by ``POST /api/v1/auth/session``.
``/health``, ``/ready``, the auth endpoints and the static UI stay public.

Accepted keys: the env key (and ``OPENGRADE_API_KEY_PREVIOUS`` during rotation), both with
the ``admin`` scope, and the per-client keys of the ``api_keys`` table (``admin`` / ``read``
/ ``ingest``, see :mod:`opengrade_server.application.api_keys`). A valid key outside its
scope gets ``403``.

The session cookie never holds a key: it is ``<subject>.<expiry>.<HMAC(env key, ...)>``
where the subject is ``env`` or the id of a table key, so revoking that key or rotating the
env key ends the session.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
import uuid
from dataclasses import dataclass

from fastapi import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from opengrade_server.application.api_keys import api_key_store
from opengrade_server.config import Settings, get_settings

SESSION_COOKIE = "opengrade_session"
OTLP_TRACES_PATH = "/v1/traces"
AUTH_STATUS_PATH = "/api/v1/auth/status"
AUTH_SESSION_PATH = "/api/v1/auth/session"
API_KEYS_PATH = "/api/v1/api-keys"
LLM_SETTINGS_PATH = "/api/v1/settings/llm"
ENV_SUBJECT = "env"
_SESSION_CONTEXT = b"opengrade-ui-session"
_READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# What an ``ingest`` key may do: send traces, scores / feedback and live interactions, and
# list projects so the SDK can resolve a project slug to its id.
_INGEST_ROUTES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("POST", re.compile(r"^/v1/traces/?$")),
    ("POST", re.compile(r"^/api/v1/projects/[^/]+/trace-scores/?$")),
    ("POST", re.compile(r"^/api/v1/projects/[^/]+/live-interactions/?$")),
    ("GET", re.compile(r"^/api/v1/projects/?$")),
)


@dataclass(frozen=True, slots=True)
class Principal:
    """Who is calling: the env key or a key of the ``api_keys`` table."""

    subject: str  # ENV_SUBJECT or the table key id
    name: str
    scope: str


ENV_PRINCIPAL = Principal(subject=ENV_SUBJECT, name="OPENGRADE_API_KEY", scope="admin")


def _is_protected(path: str) -> bool:
    if path in (AUTH_STATUS_PATH, AUTH_SESSION_PATH):
        return False
    return path.startswith("/api/") or path.rstrip("/") == OTLP_TRACES_PATH


def scope_allows(scope: str, method: str, path: str) -> bool:
    if scope == "admin":
        return True
    if path.startswith(API_KEYS_PATH) or path.startswith(LLM_SETTINGS_PATH):
        return False
    if scope == "read":
        return method in _READ_METHODS and path.startswith("/api/")
    if scope == "ingest":
        return any(m == method and pattern.match(path) for m, pattern in _INGEST_ROUTES)
    return False


def key_matches(candidate: str, settings: Settings) -> bool:
    """Constant-time check of ``candidate`` against the env key and the previous one."""
    raw = candidate.strip().encode()
    matched = False
    for key in settings.accepted_api_keys():
        # No early exit: the time taken does not reveal which key matched.
        matched |= hmac.compare_digest(raw, key.encode())
    return matched and bool(raw)


def _sign(key: str, subject: str, expires_at: int) -> str:
    message = b".".join((_SESSION_CONTEXT, subject.encode(), str(expires_at).encode()))
    return hmac.new(key.encode(), message, hashlib.sha256).hexdigest()


def issue_session_token(
    settings: Settings, subject: str = ENV_SUBJECT, *, now: float | None = None
) -> tuple[str, int]:
    """Session cookie value signed with the current env key, and its lifetime in seconds."""
    key = settings.accepted_api_keys()[0]
    max_age = int(settings.ui_session_hours * 3600)
    expires_at = int(now if now is not None else time.time()) + max_age
    return f"{subject}.{expires_at}.{_sign(key, subject, expires_at)}", max_age


def session_subject(token: str, settings: Settings, *, now: float | None = None) -> str | None:
    """The subject of a valid, unexpired session token, else ``None``."""
    subject, _, rest = token.partition(".")
    expires_raw, _, signature = rest.partition(".")
    if not subject or not expires_raw.isdigit() or not signature:
        return None
    expires_at = int(expires_raw)
    if expires_at <= (now if now is not None else time.time()):
        return None
    matched = False
    for key in settings.accepted_api_keys():
        matched |= hmac.compare_digest(signature, _sign(key, subject, expires_at))
    return subject if matched else None


def _cookie_value(cookie_header: str, name: str) -> str | None:
    for part in cookie_header.split(";"):
        cookie_name, sep, value = part.strip().partition("=")
        if sep and cookie_name == name:
            return value
    return None


async def principal_for_key(key: str, settings: Settings) -> Principal | None:
    if key_matches(key, settings):
        return ENV_PRINCIPAL
    record = await api_key_store.find_by_key(key.strip())
    if record is None:
        return None
    return Principal(subject=str(record.id), name=record.name, scope=record.scope)


async def principal_for_subject(subject: str) -> Principal | None:
    if subject == ENV_SUBJECT:
        return ENV_PRINCIPAL
    try:
        key_id = uuid.UUID(subject)
    except ValueError:
        return None
    record = await api_key_store.find_by_id(key_id)
    if record is None or record.scope == "ingest":
        return None
    return Principal(subject=str(record.id), name=record.name, scope=record.scope)


async def resolve_principal(headers: dict[str, str], settings: Settings) -> Principal | None:
    """The caller behind a bearer key or UI session cookie; ``headers`` are lower-case."""
    authorization = headers.get("authorization", "")
    scheme, _, credentials = authorization.partition(" ")
    if scheme.lower() == "bearer" and credentials.strip():
        return await principal_for_key(credentials, settings)
    token = _cookie_value(headers.get("cookie", ""), SESSION_COOKIE)
    if token is None:
        return None
    subject = session_subject(token, settings)
    return await principal_for_subject(subject) if subject is not None else None


def get_principal(request: Request) -> Principal | None:
    """Caller set by ``ApiKeyAuthMiddleware`` when auth is on; ``None`` when auth is off."""
    return getattr(request.state, "principal", None)


async def _send_json(send: Send, status: int, detail: str, *, challenge: bool) -> None:
    body = json.dumps({"detail": detail}).encode()
    headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode()),
    ]
    if challenge:
        headers.append((b"www-authenticate", b'Bearer realm="opengrade"'))
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


class ApiKeyAuthMiddleware:
    """``401`` without a valid key, ``403`` outside the key's scope (when auth is on)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if scope["type"] != "http" or not _is_protected(path):
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
        principal = await resolve_principal(headers, settings)
        if principal is None:
            await _send_json(
                send,
                401,
                "missing or invalid API key (Authorization: Bearer <key>)",
                challenge=True,
            )
            return
        method = scope.get("method", "GET")
        if not scope_allows(principal.scope, method, path):
            await _send_json(
                send,
                403,
                f"API key {principal.name!r} has the {principal.scope!r} scope, "
                f"which does not allow {method} {path}",
                challenge=False,
            )
            return
        scope.setdefault("state", {})["principal"] = principal
        await self.app(scope, receive, send)
