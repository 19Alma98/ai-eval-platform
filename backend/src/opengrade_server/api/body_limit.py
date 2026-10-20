"""Capped request / upload body readers.

Content-Length is checked first when present; the stream is then read in chunks
so oversized bodies never fully buffer into memory.
"""

from __future__ import annotations

from fastapi import Request, UploadFile


class BodyTooLarge(Exception):
    """Raised when a request or upload exceeds the configured byte cap."""


async def read_body_capped(request: Request, max_bytes: int) -> bytes:
    """Read the request body, rejecting when it would exceed ``max_bytes``."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > max_bytes:
        raise BodyTooLarge()

    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > max_bytes:
            raise BodyTooLarge()
        body += chunk
    return bytes(body)


async def read_upload_capped(file: UploadFile, max_bytes: int) -> bytes:
    """Read an uploaded file in chunks, rejecting when it would exceed ``max_bytes``."""
    body = bytearray()
    chunk_size = 64 * 1024
    while True:
        chunk = await file.read(chunk_size)
        if not chunk:
            break
        if len(body) + len(chunk) > max_bytes:
            raise BodyTooLarge()
        body += chunk
    return bytes(body)
