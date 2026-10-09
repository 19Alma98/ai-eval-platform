"""Smoke: default RAG pack kinds resolve to evaluators and score a sample."""

from __future__ import annotations

import pytest

from aiobs.domain.metrics_set import DEFAULT_RAG_SET_ENTRIES
from aiobs.evaluation import bootstrap_evaluators
from aiobs.evaluation.protocol import EvaluationSample
from aiobs.evaluation.registry import clear_registry, create_evaluator
from support.fake_llm import ScriptedJudgeLlm

_SAMPLE = EvaluationSample(
    input="How many PTO days?",
    expected_output="26 days via the portal.",
    actual_output="You get 26 days of PTO.",
    context={"documents": [{"id": "kb-1", "text": "Full-time staff get 26 days of PTO."}]},
    metadata={"expected_doc_ids": ["kb-1"], "must_contain": ["26"]},
)


@pytest.mark.asyncio
async def test_default_pack_kinds_score_a_rag_sample() -> None:
    clear_registry()
    llm = ScriptedJudgeLlm()
    bootstrap_evaluators(llm, default_model="smoke-judge")
    try:
        kinds = [e.kind for e in DEFAULT_RAG_SET_ENTRIES]
        assert "context_recall" in kinds
        assert "answer_relevance" in kinds
        for entry in DEFAULT_RAG_SET_ENTRIES:
            if not entry.enabled:
                continue
            evaluator = create_evaluator(entry.kind, {"kind": entry.kind, **entry.config})
            result = await evaluator.evaluate(_SAMPLE)
            assert result.label != "ERROR", (entry.kind, result.explanation)
            # Judges and must_contain should produce a numeric score on this sample.
            if entry.kind in {
                "context_recall",
                "context_precision",
                "groundedness",
                "correctness",
                "answer_relevance",
                "must_contain",
                "hit_at_k",
                "recall_at_k",
                "mrr",
            }:
                assert result.score is not None, entry.kind
    finally:
        clear_registry()
