"""HTTP Content-Encoding helpers for OTLP ingest."""

from __future__ import annotations

import gzip
import io
import zlib

_CHUNK = 64 * 1024


class BodyTooLargeError(Exception):
    """Decompressed (or identity) body exceeds the configured size cap."""


class UnsupportedContentEncodingError(Exception):
    def __init__(self, encoding: str) -> None:
        self.encoding = encoding
        super().__init__(f"Unsupported Content-Encoding: {encoding}")


class BodyDecodeError(Exception):
    """Wire bytes could not be decompressed."""


def decompress_http_body(
    wire: bytes,
    content_encoding: str | None,
    *,
    max_bytes: int,
) -> bytes:
    """Return the request body, decompressing gzip/deflate when advertised.

    Enforces ``max_bytes`` on the decompressed (or identity) payload so a small
    compressed blob cannot expand past the ingest limit.
    """
    encoding = (content_encoding or "").split(",")[0].strip().lower()
    if not encoding or encoding == "identity":
        if len(wire) > max_bytes:
            raise BodyTooLargeError()
        return wire
    if encoding == "gzip":
        return _gzip_decompress_capped(wire, max_bytes)
    if encoding == "deflate":
        return _deflate_decompress_capped(wire, max_bytes)
    raise UnsupportedContentEncodingError(encoding)


def _gzip_decompress_capped(wire: bytes, max_bytes: int) -> bytes:
    out = bytearray()
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(wire), mode="rb") as handle:
            while True:
                chunk = handle.read(_CHUNK)
                if not chunk:
                    break
                out.extend(chunk)
                if len(out) > max_bytes:
                    raise BodyTooLargeError()
    except BodyTooLargeError:
        raise
    except OSError as exc:
        raise BodyDecodeError(f"Invalid gzip payload: {exc}") from exc
    return bytes(out)


def _deflate_decompress_capped(wire: bytes, max_bytes: int) -> bytes:
    # OTel "deflate" is zlib-wrapped; some clients send raw DEFLATE.
    last_error: Exception | None = None
    for wbits in (zlib.MAX_WBITS, -zlib.MAX_WBITS):
        try:
            return _zlib_decompress_capped(wire, max_bytes, wbits)
        except BodyTooLargeError:
            raise
        except zlib.error as exc:
            last_error = exc
    raise BodyDecodeError(f"Invalid deflate payload: {last_error}") from last_error


def _zlib_decompress_capped(wire: bytes, max_bytes: int, wbits: int) -> bytes:
    decompressor = zlib.decompressobj(wbits)
    out = bytearray()
    offset = 0
    while offset < len(wire):
        chunk = decompressor.decompress(wire[offset : offset + _CHUNK], max_bytes - len(out) + 1)
        offset += _CHUNK
        out.extend(chunk)
        if len(out) > max_bytes:
            raise BodyTooLargeError()
    out.extend(decompressor.flush())
    if len(out) > max_bytes:
        raise BodyTooLargeError()
    return bytes(out)
