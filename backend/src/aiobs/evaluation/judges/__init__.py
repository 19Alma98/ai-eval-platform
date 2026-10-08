"""LLM judges: prompts, parsing, claim and rubric scoring."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from aiobs.domain.repositories import JudgeClaimCacheRepository
from aiobs.evaluation.judges.cache import InMemoryJudgeClaimCache
from aiobs.evaluation.judges.evaluators import JUDGE_KINDS, JudgeDefaults, create_llm_judge
from aiobs.evaluation.protocol import Evaluator, LlmClient


def make_llm_judge_factory(
    kind: str,
    llm: LlmClient,
    *,
    default_model: str | None = None,
    claim_cache: JudgeClaimCacheRepository | None = None,
) -> Callable[[dict[str, Any]], Evaluator]:
    defaults = JudgeDefaults(model=default_model)
    cache = claim_cache if claim_cache is not None else InMemoryJudgeClaimCache()

    def factory(config: dict[str, Any]) -> Evaluator:
        return create_llm_judge(kind, config, llm, defaults=defaults, claim_cache=cache)

    return factory


__all__ = ["JUDGE_KINDS", "make_llm_judge_factory"]
