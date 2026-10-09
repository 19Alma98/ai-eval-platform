from __future__ import annotations

import json
import mimetypes
import os
from pathlib import Path
from typing import Any, TypeVar

import httpx2
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class AiobsAPIError(RuntimeError):
    """Raised when the platform API returns a non-2xx response."""

    def __init__(self, status: int, body: str, *, detail: Any = None) -> None:
        self.status = status
        self.body = body
        self.detail = detail
        super().__init__(f"HTTP {status}: {body}")


def _parse_error_detail(body: str) -> Any:
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return None
    if isinstance(data, dict) and "detail" in data:
        return data["detail"]
    return None


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
        response = self._client.request(
            method,
            path,
            json=body,
            params=query,
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
        response = self._client.request(
            method,
            path,
            params=query,
            files={file_field: (filename, content, ctype)},
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
        if response.status_code >= 400:
            detail = _parse_error_detail(response.text)
            raise AiobsAPIError(response.status_code, response.text, detail=detail)
        if not response.content:
            return None
        return response.json()


def resolve_api_base_url(base_url: str | None = None) -> str:
    """Resolve API host from arg or ``AIOBS_API_BASE_URL`` (default localhost:8000)."""
    if base_url is not None and base_url.strip():
        return base_url.rstrip("/")
    env = os.getenv("AIOBS_API_BASE_URL") or os.getenv("AIOBS_BASE_URL")
    if env and env.strip():
        return env.rstrip("/")
    return "http://localhost:8000"


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
