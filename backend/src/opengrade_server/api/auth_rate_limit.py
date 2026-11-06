from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Mapping
from typing import Any

from opengrade_server.config import Settings, get_settings


class AuthFailedRateLimiter:
    """Sliding one-minute window of failures; lockout after the threshold."""

    def __init__(self, *, attempts_per_minute: int, lockout_seconds: int) -> None:
        self._limit = max(0, attempts_per_minute)
        self._lockout = max(1, lockout_seconds)
        self._failures: dict[str, deque[float]] = defaultdict(deque)
        self._locked_until: dict[str, float] = {}

    @property
    def enabled(self) -> bool:
        return self._limit > 0

    def retry_after(self, client_ip: str) -> int | None:
        if not self.enabled:
            return None
        until = self._locked_until.get(client_ip)
        if until is None:
            return None
        remaining = int(until - time.monotonic())
        if remaining <= 0:
            self._locked_until.pop(client_ip, None)
            return None
        return remaining

    def record_failure(self, client_ip: str) -> int | None:
        """Record a failed auth attempt. Returns Retry-After seconds if locked out."""
        if not self.enabled:
            return None
        now = time.monotonic()
        until = self._locked_until.get(client_ip)
        if until is not None and until > now:
            return max(1, int(until - now))
        window = self._failures[client_ip]
        cutoff = now - 60.0
        while window and window[0] < cutoff:
            window.popleft()
        window.append(now)
        if len(window) < self._limit:
            return None
        self._locked_until[client_ip] = now + self._lockout
        window.clear()
        return self._lockout


_limiter: AuthFailedRateLimiter | None = None


def get_auth_failed_rate_limiter(settings: Settings | None = None) -> AuthFailedRateLimiter:
    global _limiter
    cfg = settings or get_settings()
    if _limiter is None:
        _limiter = AuthFailedRateLimiter(
            attempts_per_minute=cfg.auth_failed_attempts_per_minute,
            lockout_seconds=cfg.auth_failed_lockout_seconds,
        )
    return _limiter


def reset_auth_failed_rate_limiter_for_tests() -> None:
    global _limiter
    _limiter = None


def client_ip_from_scope(scope: Mapping[str, Any]) -> str:
    client = scope.get("client")
    if client and len(client) >= 1 and client[0]:
        return str(client[0])
    return "unknown"
