"""Outbound webhook delivery for alert notifications."""

from __future__ import annotations

from typing import Any

import httpx2

from opengrade_server.config import get_settings


class HttpWebhookNotifier:
    def __init__(
        self,
        *,
        timeout_seconds: float | None = None,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        self._timeout = timeout_seconds
        self._transport = transport

    async def send(self, url: str, payload: dict[str, Any]) -> str | None:
        timeout = self._timeout or get_settings().alert_webhook_timeout_seconds
        try:
            async with httpx2.AsyncClient(timeout=timeout, transport=self._transport) as client:
                response = await client.post(url, json=payload)
        except httpx2.HTTPError as exc:
            return f"{type(exc).__name__}: {exc}"[:2000]
        if response.status_code >= 400:
            return f"HTTP {response.status_code}: {response.text[:500]}"
        return None
