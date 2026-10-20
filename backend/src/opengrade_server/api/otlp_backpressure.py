"""Per-process OTLP ingest gates (rate, inflight, pending scores)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from opengrade_server.config import Settings, get_settings


@dataclass(frozen=True)
class OtlpRejected(Exception):
    status_code: int
    retry_after: int
    detail: str

    def __str__(self) -> str:
        return self.detail


class OtlpBackpressure:
    """Token-bucket RPS + inflight counter + pending-score depth check."""

    def __init__(
        self,
        *,
        rate_per_second: float,
        max_inflight: int,
        max_pending_scores: int,
        retry_after_seconds: int,
        burst: float | None = None,
    ) -> None:
        self._rate = max(0.0, rate_per_second)
        self._burst = burst if burst is not None else max(1.0, self._rate)
        self._tokens = self._burst
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()
        self._max_inflight = max(1, max_inflight)
        self._max_pending = max(0, max_pending_scores)
        self._retry_after = max(1, retry_after_seconds)
        self._held = 0

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._last_refill = now
        if self._rate > 0:
            self._tokens = min(self._burst, self._tokens + elapsed * self._rate)

    async def acquire(self, *, pending_scores: int) -> None:
        async with self._lock:
            if pending_scores >= self._max_pending:
                raise OtlpRejected(
                    status_code=503,
                    retry_after=self._retry_after,
                    detail="OTLP ingest overloaded: too many pending scores",
                )
            if self._held >= self._max_inflight:
                raise OtlpRejected(
                    status_code=503,
                    retry_after=self._retry_after,
                    detail="OTLP ingest overloaded: too many in-flight requests",
                )
            self._refill()
            if self._rate > 0 and self._tokens < 1.0:
                raise OtlpRejected(
                    status_code=429,
                    retry_after=self._retry_after,
                    detail="OTLP rate limit exceeded",
                )
            if self._rate > 0:
                self._tokens -= 1.0
            self._held += 1

    def release(self) -> None:
        if self._held > 0:
            self._held -= 1

    @asynccontextmanager
    async def slot(self, *, pending_scores: int) -> AsyncIterator[None]:
        await self.acquire(pending_scores=pending_scores)
        try:
            yield
        finally:
            self.release()


_gate: OtlpBackpressure | None = None


def get_otlp_backpressure(settings: Settings | None = None) -> OtlpBackpressure:
    global _gate
    cfg = settings or get_settings()
    if _gate is None:
        _gate = OtlpBackpressure(
            rate_per_second=cfg.otlp_rate_limit_per_second,
            max_inflight=cfg.otlp_max_inflight,
            max_pending_scores=cfg.otlp_max_pending_scores,
            retry_after_seconds=cfg.otlp_retry_after_seconds,
        )
    return _gate


def reset_otlp_backpressure_for_tests() -> None:
    global _gate
    _gate = None
