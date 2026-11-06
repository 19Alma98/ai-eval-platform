"""UI session endpoints: exchange an API key for an ``HttpOnly`` cookie.

This is not a user login: there are no accounts. The browser cannot send the
``Authorization`` header for every asset and keeping the key in JavaScript storage would
expose it to any script on the page, so the UI posts the key once and gets a signed,
expiring cookie instead. ``ingest`` keys cannot open the dashboard.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from opengrade_server.api.auth import (
    AUTH_SESSION_PATH,
    AUTH_STATUS_PATH,
    SESSION_COOKIE,
    issue_session_token,
    principal_for_key,
    resolve_principal,
)
from opengrade_server.api.auth_rate_limit import (
    client_ip_from_scope,
    get_auth_failed_rate_limiter,
)
from opengrade_server.config import get_settings

router = APIRouter(tags=["auth"])


class AuthStatusResponse(BaseModel):
    auth_required: bool
    authenticated: bool
    scope: str | None = None
    key_name: str | None = None


class CreateSessionRequest(BaseModel):
    api_key: str = Field(min_length=1, max_length=1024)


def _request_headers(request: Request) -> dict[str, str]:
    return {name.lower(): value for name, value in request.headers.items()}


@router.get(AUTH_STATUS_PATH, response_model=AuthStatusResponse)
async def auth_status(request: Request) -> AuthStatusResponse:
    settings = get_settings()
    if not settings.accepted_api_keys():
        return AuthStatusResponse(auth_required=False, authenticated=True, scope="admin")
    principal = await resolve_principal(_request_headers(request), settings)
    if principal is None or principal.scope == "ingest":
        return AuthStatusResponse(auth_required=True, authenticated=False)
    return AuthStatusResponse(
        auth_required=True,
        authenticated=True,
        scope=principal.scope,
        key_name=principal.name,
    )


@router.post(AUTH_SESSION_PATH, status_code=status.HTTP_204_NO_CONTENT)
async def create_session(body: CreateSessionRequest, request: Request) -> Response:
    settings = get_settings()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    if not settings.accepted_api_keys():
        return response
    client_ip = client_ip_from_scope(request.scope)
    limiter = get_auth_failed_rate_limiter(settings)
    locked = limiter.retry_after(client_ip)
    if locked is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="too many failed API key attempts; try again later",
            headers={"Retry-After": str(locked)},
        )
    principal = await principal_for_key(body.api_key, settings)
    if principal is None:
        retry_after = limiter.record_failure(client_ip)
        if retry_after is not None:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="too many failed API key attempts; try again later",
                headers={"Retry-After": str(retry_after)},
            )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid API key")
    if principal.scope == "ingest":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="ingest keys can only send traces; use a read or admin key for the dashboard",
        )
    token, max_age = issue_session_token(settings, principal.subject)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=max_age,
        httponly=True,
        # Behind a TLS proxy the scheme comes from X-Forwarded-Proto (FORWARDED_ALLOW_IPS).
        secure=request.url.scheme == "https",
        samesite="strict",
        path="/",
    )
    return response


@router.delete(AUTH_SESSION_PATH, status_code=status.HTTP_204_NO_CONTENT)
async def delete_session() -> Response:
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="strict")
    return response
