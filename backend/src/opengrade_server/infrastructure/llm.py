from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import litellm

from opengrade_server.config import Settings

if TYPE_CHECKING:
    from opengrade_server.application.llm_settings import EffectiveLlmSettings


def _default_resolve() -> EffectiveLlmSettings:
    from opengrade_server.application.llm_settings import get_effective_llm_settings_sync

    return get_effective_llm_settings_sync()


class LiteLlmClient:
    """Multi-provider LLM gateway via LiteLLM.

    Resolves model/key/base and related knobs from effective settings on each call so
    Settings UI overlays and ``.env`` key updates apply without a process restart.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        resolve: Callable[[], EffectiveLlmSettings] | None = None,
    ) -> None:
        if resolve is not None:
            self._resolve = resolve
        elif settings is not None:
            from opengrade_server.application.llm_settings import EffectiveLlmSettings as Eff

            snapshot = Eff.from_env(settings)
            self._resolve = lambda: snapshot
        else:
            self._resolve = _default_resolve

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
        from opengrade_server.evaluation.judges.errors import (
            JudgeNotConfiguredError,
            judge_needs_api_key,
        )

        cfg = self._resolve()
        resolved_model = model or cfg.model
        if not (resolved_model or "").strip():
            raise JudgeNotConfiguredError()
        if not cfg.api_key and judge_needs_api_key(resolved_model, cfg.api_base):
            raise JudgeNotConfiguredError()
        kwargs: dict[str, Any] = {
            "model": resolved_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
                *(history or []),
            ],
            "response_format": {"type": "json_object"},
            "temperature": (cfg.temperature if temperature is None else temperature),
            "timeout": cfg.timeout_seconds,
            "num_retries": cfg.max_retries,
            # Providers without e.g. seed support ignore it instead of failing.
            "drop_params": True,
        }
        resolved_seed = cfg.seed if seed is None else seed
        if resolved_seed is not None:
            kwargs["seed"] = resolved_seed
        if cfg.api_key:
            kwargs["api_key"] = cfg.api_key
        if cfg.api_base:
            kwargs["api_base"] = cfg.api_base

        response = await litellm.acompletion(**kwargs)
        return response.choices[0].message.content or ""
