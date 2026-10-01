from __future__ import annotations

import json
from typing import Any

import litellm

from aiobs.config import Settings


class LiteLlmClient:
    """Multi-provider LLM gateway via LiteLLM."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def complete_json(
        self,
        *,
        system: str,
        user: str,
        model: str | None = None,
    ) -> dict[str, Any]:
        resolved_model = model or self._settings.llm_model
        kwargs: dict[str, Any] = {
            "model": resolved_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
            "timeout": self._settings.llm_timeout_seconds,
            "num_retries": self._settings.llm_max_retries,
        }
        if self._settings.llm_api_key:
            kwargs["api_key"] = self._settings.llm_api_key
        if self._settings.llm_api_base:
            kwargs["api_base"] = self._settings.llm_api_base

        response = await litellm.acompletion(**kwargs)
        content = response.choices[0].message.content
        if not content:
            raise ValueError("LLM returned empty content")
        data = json.loads(content)
        if not isinstance(data, dict):
            raise ValueError("LLM JSON response must be an object")
        return data
