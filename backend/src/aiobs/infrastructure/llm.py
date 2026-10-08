from __future__ import annotations

from typing import Any

import litellm

from aiobs.config import Settings


class LiteLlmClient:
    """Multi-provider LLM gateway via LiteLLM."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def complete(
        self,
        *,
        system: str,
        user: str,
        model: str | None = None,
        temperature: float | None = None,
        seed: int | None = None,
        history: list[dict[str, str]] | None = None,
    ) -> str:
        kwargs: dict[str, Any] = {
            "model": model or self._settings.llm_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
                *(history or []),
            ],
            "response_format": {"type": "json_object"},
            "temperature": (self._settings.llm_temperature if temperature is None else temperature),
            "timeout": self._settings.llm_timeout_seconds,
            "num_retries": self._settings.llm_max_retries,
            # Providers without e.g. seed support ignore it instead of failing.
            "drop_params": True,
        }
        resolved_seed = self._settings.llm_seed if seed is None else seed
        if resolved_seed is not None:
            kwargs["seed"] = resolved_seed
        if self._settings.llm_api_key:
            kwargs["api_key"] = self._settings.llm_api_key
        if self._settings.llm_api_base:
            kwargs["api_base"] = self._settings.llm_api_base

        response = await litellm.acompletion(**kwargs)
        return response.choices[0].message.content or ""
