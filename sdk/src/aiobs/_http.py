from __future__ import annotations

import mimetypes
import os
from pathlib import Path
from typing import Any

import httpx2


class AiobsAPIError(RuntimeError):
    """Raised when the platform API returns a non-2xx response."""

    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self.body = body
        super().__init__(f"HTTP {status}: {body}")


class _HttpTransport:
    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 30.0,
        transport: httpx2.BaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
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

    def close(self) -> None:
        self._client.close()

    def _parse(self, response: httpx2.Response) -> Any:
        if response.status_code >= 400:
            raise AiobsAPIError(response.status_code, response.text)
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
