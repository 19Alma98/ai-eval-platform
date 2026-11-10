from __future__ import annotations

import asyncio
import json
import mimetypes
import random
import time
from collections.abc import Awaitable, Callable
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, TypeVar

import httpx2
from pydantic import BaseModel

from opengrade._config import auth_headers
from opengrade._errors import OpengradeAPIError, OpengradeConnectionError, OpengradeError

T = TypeVar("T", bound=BaseModel)

_IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE"})
_RETRY_STATUSES = frozenset({429, 503})
_MAX_ATTEMPTS = 3
_BACKOFF_BASE_S = 0.5
_RETRY_AFTER_CAP_S = 30.0

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


def _parse_retry_after(value: str | None) -> float | None:
    if value is None:
        return None
    raw = value.strip()
    if not raw:
        return None
    if raw.isdigit():
        return float(raw)
    try:
        when = parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if when.tzinfo is None:
        from datetime import UTC

        when = when.replace(tzinfo=UTC)
    delay = when.timestamp() - time.time()
    return max(0.0, delay)


def _retry_decision(
    method: str,
    *,
    attempt: int,
    status: int | None = None,
    retry_after: str | None = None,
    transport_error: bool = False,
) -> tuple[bool, float]:
    if attempt + 1 >= _MAX_ATTEMPTS:
        return False, 0.0
    if transport_error:
        # Request never completed; safe to retry any method.
        pass
    elif method.upper() not in _IDEMPOTENT_METHODS or status not in _RETRY_STATUSES:
        return False, 0.0
    parsed = _parse_retry_after(retry_after)
    if parsed is not None:
        return True, min(parsed, _RETRY_AFTER_CAP_S)
    return True, random.uniform(0.0, _BACKOFF_BASE_S * (2**attempt))


def _call_with_retry(method: str, call: Callable[[], httpx2.Response]) -> httpx2.Response:
    return _run_with_retry(method, call, sleep=time.sleep)


async def _acall_with_retry(
    method: str, call: Callable[[], Awaitable[httpx2.Response]]
) -> httpx2.Response:
    return await _arun_with_retry(method, call, sleep=asyncio.sleep)


def _run_with_retry(
    method: str,
    call: Callable[[], httpx2.Response],
    *,
    sleep: Callable[[float], None],
) -> httpx2.Response:
    last_exc: httpx2.HTTPError | None = None
    response: httpx2.Response | None = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            response = call()
        except httpx2.HTTPError as exc:
            last_exc = exc
            should, delay = _retry_decision(method, attempt=attempt, transport_error=True)
            if not should:
                raise _wrap_http_error(exc) from exc
            sleep(delay)
            continue
        should, delay = _retry_decision(
            method,
            attempt=attempt,
            status=response.status_code,
            retry_after=response.headers.get("Retry-After"),
        )
        if not should:
            return response
        sleep(delay)
    if response is not None:
        return response
    assert last_exc is not None
    raise _wrap_http_error(last_exc) from last_exc


async def _arun_with_retry(
    method: str,
    call: Callable[[], Awaitable[httpx2.Response]],
    *,
    sleep: Callable[[float], Awaitable[None]],
) -> httpx2.Response:
    last_exc: httpx2.HTTPError | None = None
    response: httpx2.Response | None = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            response = await call()
        except httpx2.HTTPError as exc:
            last_exc = exc
            should, delay = _retry_decision(method, attempt=attempt, transport_error=True)
            if not should:
                raise _wrap_http_error(exc) from exc
            await sleep(delay)
            continue
        should, delay = _retry_decision(
            method,
            attempt=attempt,
            status=response.status_code,
            retry_after=response.headers.get("Retry-After"),
        )
        if not should:
            return response
        await sleep(delay)
    if response is not None:
        return response
    assert last_exc is not None
    raise _wrap_http_error(last_exc) from last_exc


class _HttpTransport:
    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 30.0,
        transport: httpx2.BaseTransport | None = None,
        client: httpx2.Client | None = None,
        api_key: str | None = None,
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
            "headers": {
                "Accept": "application/json",
                **auth_headers(self._base_url, api_key),
            },
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
        query: dict[str, Any] | None = None,
    ) -> Any:
        response = _call_with_retry(
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
        query: dict[str, Any] | None = None,
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
        query: dict[str, Any] | None = None,
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
        query: dict[str, Any] | None = None,
    ) -> Any:
        ctype = content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
        response = _call_with_retry(
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
        query: dict[str, Any] | None = None,
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
        api_key: str | None = None,
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
            "headers": {
                "Accept": "application/json",
                **auth_headers(self._base_url, api_key),
            },
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
        query: dict[str, Any] | None = None,
    ) -> Any:
        response = await _acall_with_retry(
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
        query: dict[str, Any] | None = None,
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
        query: dict[str, Any] | None = None,
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
    """Resolve API host from ``base_url``, else the active Opengrade tracking URI."""
    if base_url is not None and base_url.strip():
        return base_url.rstrip("/")
    from opengrade._config import DEFAULT_TRACKING_URI
    from opengrade._state import tracking_uri_for

    try:
        from opengrade._opengrade import current

        return tracking_uri_for(current()._runtime)
    except RuntimeError:
        return DEFAULT_TRACKING_URI


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
