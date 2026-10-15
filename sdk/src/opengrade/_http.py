from __future__ import annotations

import asyncio
import json
import mimetypes
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, TypeVar

import httpx2
from pydantic import BaseModel

from opengrade._config import get_tracking_uri
from opengrade._errors import OpengradeAPIError, OpengradeConnectionError, OpengradeError

T = TypeVar("T", bound=BaseModel)

_CONNECT_RETRIES = 2
_CONNECT_RETRY_BACKOFF_S = 1.0

__all__ = [
    "OpengradeAPIError",
    "OpengradeConnectionError",
    "OpengradeError",
]


def _parse_error_detail(body: str) -> Any:
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return None
    if isinstance(data, dict) and "detail" in data:
        return data["detail"]
    return None


def _wrap_http_error(exc: httpx2.HTTPError) -> OpengradeConnectionError:
    return OpengradeConnectionError(f"platform unreachable: {exc}", cause=exc)


def _call_with_connect_retry(method: str, call: Callable[[], httpx2.Response]) -> httpx2.Response:
    """Run ``call()``; retry GET-like methods once on transport failure."""
    attempts = _CONNECT_RETRIES if method.upper() in {"GET", "HEAD", "OPTIONS"} else 1
    last: httpx2.HTTPError | None = None
    for attempt in range(attempts):
        try:
            return call()
        except httpx2.HTTPError as exc:
            last = exc
            if attempt + 1 >= attempts:
                break
            time.sleep(_CONNECT_RETRY_BACKOFF_S)
    assert last is not None
    raise _wrap_http_error(last) from last


async def _acall_with_connect_retry(
    method: str, call: Callable[[], Awaitable[httpx2.Response]]
) -> httpx2.Response:
    attempts = _CONNECT_RETRIES if method.upper() in {"GET", "HEAD", "OPTIONS"} else 1
    last: httpx2.HTTPError | None = None
    for attempt in range(attempts):
        try:
            return await call()
        except httpx2.HTTPError as exc:
            last = exc
            if attempt + 1 >= attempts:
                break
            await asyncio.sleep(_CONNECT_RETRY_BACKOFF_S)
    assert last is not None
    raise _wrap_http_error(last) from last


class _HttpTransport:
    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 30.0,
        transport: httpx2.BaseTransport | None = None,
        client: httpx2.Client | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._owns_client = client is None
        if client is not None:
            self._client = client
            return
        kwargs: dict[str, Any] = {
            "base_url": self._base_url,
            "timeout": timeout,
            "headers": {"Accept": "application/json"},
        }
        if transport is not None:
            kwargs["transport"] = transport
        self._client = httpx2.Client(**kwargs)

    def request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        query: dict[str, str] | None = None,
    ) -> Any:
        response = _call_with_connect_retry(
            method,
            lambda: self._client.request(method, path, json=body, params=query),
        )
        return self._parse(response)

    def request_model(
        self,
        method: str,
        path: str,
        *,
        response_model: type[T],
        body: dict[str, Any] | None = None,
        query: dict[str, str] | None = None,
    ) -> T:
        data = self.request(method, path, body=body, query=query)
        return response_model.model_validate(data)

    def request_model_list(
        self,
        method: str,
        path: str,
        *,
        response_model: type[T],
        body: dict[str, Any] | None = None,
        query: dict[str, str] | None = None,
    ) -> list[T]:
        data = self.request(method, path, body=body, query=query)
        if not isinstance(data, list):
            raise TypeError(f"expected list response, got {type(data).__name__}")
        return [response_model.model_validate(item) for item in data]

    def request_multipart(
        self,
        method: str,
        path: str,
        *,
        file_field: str,
        filename: str,
        content: bytes,
        content_type: str | None = None,
        query: dict[str, str] | None = None,
    ) -> Any:
        ctype = content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
        response = _call_with_connect_retry(
            method,
            lambda: self._client.request(
                method,
                path,
                params=query,
                files={file_field: (filename, content, ctype)},
            ),
        )
        return self._parse(response)

    def request_multipart_model(
        self,
        method: str,
        path: str,
        *,
        response_model: type[T],
        file_field: str,
        filename: str,
        content: bytes,
        content_type: str | None = None,
        query: dict[str, str] | None = None,
    ) -> T:
        data = self.request_multipart(
            method,
            path,
            file_field=file_field,
            filename=filename,
            content=content,
            content_type=content_type,
            query=query,
        )
        return response_model.model_validate(data)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _parse(self, response: httpx2.Response) -> Any:
        return _parse_response(response)


class _AsyncHttpTransport:
    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 30.0,
        transport: httpx2.AsyncBaseTransport | None = None,
        client: httpx2.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._owns_client = client is None
        if client is not None:
            self._client = client
            return
        kwargs: dict[str, Any] = {
            "base_url": self._base_url,
            "timeout": timeout,
            "headers": {"Accept": "application/json"},
        }
        if transport is not None:
            kwargs["transport"] = transport
        self._client = httpx2.AsyncClient(**kwargs)

    async def request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        query: dict[str, str] | None = None,
    ) -> Any:
        response = await _acall_with_connect_retry(
            method,
            lambda: self._client.request(method, path, json=body, params=query),
        )
        return _parse_response(response)

    async def request_model(
        self,
        method: str,
        path: str,
        *,
        response_model: type[T],
        body: dict[str, Any] | None = None,
        query: dict[str, str] | None = None,
    ) -> T:
        data = await self.request(method, path, body=body, query=query)
        return response_model.model_validate(data)

    async def request_model_list(
        self,
        method: str,
        path: str,
        *,
        response_model: type[T],
        body: dict[str, Any] | None = None,
        query: dict[str, str] | None = None,
    ) -> list[T]:
        data = await self.request(method, path, body=body, query=query)
        if not isinstance(data, list):
            raise TypeError(f"expected list response, got {type(data).__name__}")
        return [response_model.model_validate(item) for item in data]

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def _parse_response(response: httpx2.Response) -> Any:
    if response.status_code >= 400:
        detail = _parse_error_detail(response.text)
        raise OpengradeAPIError(response.status_code, response.text, detail=detail)
    if not response.content:
        return None
    return response.json()


def resolve_api_base_url(base_url: str | None = None) -> str:
    """Resolve API host from arg, else the tracking URI (see ``opengrade.get_tracking_uri``)."""
    if base_url is not None and base_url.strip():
        return base_url.rstrip("/")
    return get_tracking_uri()


def read_upload(
    path: str | Path | None = None,
    *,
    file: tuple[str, bytes] | None = None,
) -> tuple[str, bytes]:
    """Normalize a filesystem path or ``(filename, bytes)`` upload pair."""
    if file is not None:
        if path is not None:
            raise ValueError("pass either path or file, not both")
        filename, content = file
        if not filename:
            raise ValueError("file tuple requires a non-empty filename")
        return filename, content
    if path is None:
        raise ValueError("pass path or file")
    p = Path(path)
    return p.name, p.read_bytes()
