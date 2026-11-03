"""UI session endpoints: exchange the API key for an ``HttpOnly`` cookie.

This is not a user login: there are no accounts. The browser cannot send the
``Authorization`` header for every asset and keeping the key in JavaScript storage would
expose it to any script on the page, so the UI posts the key once and gets a signed,
expiring cookie instead.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from opengrade_server.api.auth import (
    AUTH_SESSION_PATH,
    AUTH_STATUS_PATH,
    SESSION_COOKIE,
    headers_authenticated,
    issue_session_token,
    key_matches,
)
from opengrade_server.config import get_settings

router = APIRouter(tags=["auth"])


class AuthStatusResponse(BaseModel):
    auth_required: bool
    authenticated: bool


class CreateSessionRequest(BaseModel):
    api_key: str = Field(min_length=1, max_length=1024)


def _request_headers(request: Request) -> dict[str, str]:
    return {name.lower(): value for name, value in request.headers.items()}


@router.get(AUTH_STATUS_PATH, response_model=AuthStatusResponse)
async def auth_status(request: Request) -> AuthStatusResponse:
    settings = get_settings()
    if not settings.accepted_api_keys():
        return AuthStatusResponse(auth_required=False, authenticated=True)
    return AuthStatusResponse(
        auth_required=True,
        authenticated=headers_authenticated(_request_headers(request), settings),
    )


@router.post(AUTH_SESSION_PATH, status_code=status.HTTP_204_NO_CONTENT)
async def create_session(body: CreateSessionRequest, request: Request) -> Response:
    settings = get_settings()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    if not settings.accepted_api_keys():
        return response
    if not key_matches(body.api_key, settings):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid API key")
    token, max_age = issue_session_token(settings)
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
