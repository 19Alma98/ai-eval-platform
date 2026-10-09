"""Evaluation engine — evaluator protocol, registry, built-ins, runner."""

from __future__ import annotations

from aiobs_server.domain.repositories import JudgeClaimCacheRepository
from aiobs_server.evaluation.deterministic import register_deterministic_evaluators
from aiobs_server.evaluation.judges import JUDGE_KINDS, make_llm_judge_factory
from aiobs_server.evaluation.protocol import (
    EvaluationResult,
    EvaluationSample,
    Evaluator,
    LlmClient,
)
from aiobs_server.evaluation.registry import (
    create_evaluator,
    list_registered_kinds,
    register_evaluator,
)
from aiobs_server.evaluation.runner import EvaluationRunner


def bootstrap_evaluators(
    llm: LlmClient | None = None,
    *,
    default_model: str | None = None,
    claim_cache: JudgeClaimCacheRepository | None = None,
) -> None:
    """Register built-in deterministic and (optionally) LLM judge evaluators."""
    register_deterministic_evaluators()
    if llm is not None:
        for kind in JUDGE_KINDS:
            register_evaluator(
                kind,
                make_llm_judge_factory(
                    kind, llm, default_model=default_model, claim_cache=claim_cache
                ),
            )


__all__ = [
    "EvaluationResult",
    "EvaluationRunner",
    "EvaluationSample",
    "Evaluator",
    "LlmClient",
    "bootstrap_evaluators",
    "create_evaluator",
    "list_registered_kinds",
    "register_evaluator",
]
