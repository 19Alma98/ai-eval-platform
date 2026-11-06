"""Register built-in evaluators using the current effective LLM settings."""

from __future__ import annotations

from opengrade_server.application.llm_settings import get_effective_llm_settings_sync
from opengrade_server.evaluation import bootstrap_evaluators
from opengrade_server.evaluation.registry import clear_registry
from opengrade_server.infrastructure.llm import LiteLlmClient
from opengrade_server.infrastructure.repositories import SqlJudgeClaimCache


def ensure_evaluators_registered() -> None:
    """Clear and re-register judges so ``default_model`` matches effective settings."""
    cfg = get_effective_llm_settings_sync()
    clear_registry()
    bootstrap_evaluators(
        LiteLlmClient(),
        default_model=cfg.model,
        claim_cache=SqlJudgeClaimCache(),
    )
