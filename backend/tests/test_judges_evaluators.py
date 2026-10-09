from __future__ import annotations

from typing import Any

import pytest

from aiobs_server.evaluation import bootstrap_evaluators
from aiobs_server.evaluation.judges.cache import InMemoryJudgeClaimCache
from aiobs_server.evaluation.judges.evaluators import JudgeDefaults, create_llm_judge
from aiobs_server.evaluation.protocol import EvaluationSample
from aiobs_server.evaluation.registry import clear_registry, create_evaluator
from support.fake_llm import ScriptedJudgeLlm

_DEFAULTS = JudgeDefaults(model="judge-default")
_DOCS = {"documents": [{"id": "kb-1", "text": "Full-time staff get 26 days of PTO."}]}


def _sample(**overrides: Any) -> EvaluationSample:
    values: dict[str, Any] = {
        "input": "How many PTO days?",
        "expected_output": "26 days, requested via the portal.",
        "actual_output": "You get 26 days of PTO.",
        "context": _DOCS,
        "metadata": {"expected_doc_ids": ["GOLD-DOC"]},
    }
    values.update(overrides)
    return EvaluationSample(**values)


def _judge(kind: str, llm: ScriptedJudgeLlm, config: dict[str, Any] | None = None, cache=None):
    return create_llm_judge(kind, config or {}, llm, defaults=_DEFAULTS, claim_cache=cache)


# --- configuration -------------------------------------------------------------


def test_unknown_kind_and_invalid_config_raise() -> None:
    llm = ScriptedJudgeLlm()
    with pytest.raises(ValueError, match="Unknown LLM judge kind"):
        _judge("faithfulness", llm)
    with pytest.raises(ValueError, match="method"):
        _judge("answer_relevance", llm, {"method": "claims"})
    with pytest.raises(ValueError, match="scoring"):
        _judge("correctness", llm, {"scoring": "precision"})
    with pytest.raises(ValueError, match="max_claims"):
        _judge("groundedness", llm, {"max_claims": 0})


def test_prompt_version_reflects_method() -> None:
    llm = ScriptedJudgeLlm()
    assert _judge("groundedness", llm).prompt_version == "groundedness.claims.v3"
    assert _judge("groundedness", llm, {"method": "rubric"}).prompt_version == (
        "groundedness.rubric.v3"
    )
    assert _judge("answer_relevance", llm).prompt_version == "answer_relevance.rubric.v3"


# --- groundedness ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_groundedness_claims_scores_supported_ratio() -> None:
    llm = ScriptedJudgeLlm(
        {
            "extract_answer_claims": {"claims": ["26 days of PTO", "Requested by email"]},
            "verify_against_documents": {
                "verdicts": [
                    {
                        "reasoning": "r",
                        "verdict": "supported",
                        "doc_ids": ["kb-1"],
                        "quote": "26 days",
                    },
                    {"reasoning": "r", "verdict": "not_supported"},
                ]
            },
        }
    )
    result = await _judge("groundedness", llm, {"model": "judge-x"}).evaluate(_sample())

    assert result.score == 0.5
    assert result.label is None
    assert result.explanation == '1/2 claims supported; not supported: "Requested by email"'
    meta = result.metadata
    assert meta["method"] == "claims"
    assert meta["prompt_version"] == "groundedness.claims.v3"
    assert meta["model"] == "judge-x"
    assert meta["n_claims"] == 2 and meta["n_supported"] == 1
    assert meta["claims"][0]["doc_ids"] == ["kb-1"]
    assert meta["llm_calls"] == 2
    assert llm.steps() == ["extract_answer_claims", "verify_against_documents"]
    assert all(call["model"] == "judge-x" for call in llm.calls)


@pytest.mark.asyncio
async def test_groundedness_never_sees_gold() -> None:
    llm = ScriptedJudgeLlm()
    await _judge("groundedness", llm).evaluate(_sample(expected_output="GOLD-ANSWER-TEXT"))
    for call in llm.calls:
        assert "GOLD-ANSWER-TEXT" not in call["user"]
        assert "GOLD-DOC" not in call["user"]
    assert "Full-time staff get 26 days" in llm.calls[1]["user"]


@pytest.mark.asyncio
async def test_groundedness_no_claims_is_skipped() -> None:
    llm = ScriptedJudgeLlm({"extract_answer_claims": {"claims": []}})
    result = await _judge("groundedness", llm).evaluate(_sample(actual_output="I don't know."))
    assert result.label == "SKIPPED"
    assert result.score is None
    assert result.explanation.startswith("no_factual_claims")
    assert llm.steps() == ["extract_answer_claims"]


@pytest.mark.asyncio
async def test_groundedness_prechecks_do_not_call_llm() -> None:
    llm = ScriptedJudgeLlm()
    judge = _judge("groundedness", llm)
    assert (await judge.evaluate(_sample(context=None))).label == "SKIPPED"
    empty = await judge.evaluate(_sample(context={"documents": []}))
    assert (empty.label, empty.score) == ("FAIL", 0.0)
    assert (await judge.evaluate(_sample(actual_output=None))).label == "SKIPPED"
    assert llm.calls == []


@pytest.mark.asyncio
async def test_groundedness_max_claims_truncates() -> None:
    llm = ScriptedJudgeLlm({"extract_answer_claims": {"claims": ["a", "b", "c"]}})
    result = await _judge("groundedness", llm, {"max_claims": 2}).evaluate(_sample())
    assert result.metadata["n_claims"] == 2
    assert result.metadata["claims_truncated"] is True


@pytest.mark.asyncio
async def test_groundedness_rubric_method() -> None:
    llm = ScriptedJudgeLlm({"rubric_groundedness": {"reasoning": "mostly", "level": 4}})
    result = await _judge("groundedness", llm, {"method": "rubric"}).evaluate(_sample())
    assert result.score == 0.75
    assert result.label is None
    assert result.explanation == "level 4/5: mostly"
    assert result.metadata["level"] == 4
    assert llm.steps() == ["rubric_groundedness"]


# --- correctness -----------------------------------------------------------------


def _coverage(*verdicts: str) -> dict[str, Any]:
    return {"verdicts": [{"reasoning": "r", "verdict": v} for v in verdicts]}


@pytest.mark.asyncio
async def test_correctness_recall_ignores_extra_answer_facts() -> None:
    llm = ScriptedJudgeLlm(
        {
            "extract_reference_claims": {"claims": ["26 days", "via the portal"]},
            "verify_reference_coverage": _coverage("covered", "missing"),
        }
    )
    result = await _judge("correctness", llm).evaluate(_sample())
    assert result.score == 0.5
    assert result.label is None
    assert result.explanation == '1/2 reference facts covered; missing: "via the portal"'
    meta = result.metadata
    assert (meta["n_gold"], meta["n_covered"], meta["n_missing"]) == (2, 1, 1)
    assert meta["recall"] == 0.5
    assert meta["scoring"] == "recall"
    assert meta["cache_hit"] is False
    assert llm.steps() == ["extract_reference_claims", "verify_reference_coverage"]


@pytest.mark.asyncio
async def test_correctness_contradiction_scores_zero() -> None:
    llm = ScriptedJudgeLlm(
        {
            "extract_reference_claims": {"claims": ["26 days", "via the portal"]},
            "verify_reference_coverage": _coverage("contradicted", "covered"),
        }
    )
    result = await _judge("correctness", llm).evaluate(_sample(actual_output="20 days"))
    assert result.score == 0.0
    assert result.metadata["n_contradicted"] == 1
    assert "contradicted:" in result.explanation


@pytest.mark.asyncio
async def test_correctness_f1() -> None:
    llm = ScriptedJudgeLlm(
        {
            "extract_reference_claims": {"claims": ["26 days", "via the portal"]},
            "verify_reference_coverage": _coverage("covered", "missing"),
            "extract_answer_claims": {"claims": ["26 days", "unlimited carry-over"]},
            "verify_against_reference": {
                "verdicts": [
                    {"reasoning": "r", "verdict": "supported"},
                    {"reasoning": "r", "verdict": "not_supported"},
                ]
            },
        }
    )
    result = await _judge("correctness", llm, {"scoring": "f1"}).evaluate(_sample())
    assert result.metadata["precision"] == 0.5
    assert result.metadata["recall"] == 0.5
    assert result.score == pytest.approx(0.5)
    assert len(result.metadata["answer_claims"]) == 2
    assert result.metadata["llm_calls"] == 4


@pytest.mark.asyncio
async def test_correctness_reuses_cached_gold_claims() -> None:
    cache = InMemoryJudgeClaimCache()
    first_llm = ScriptedJudgeLlm({"extract_reference_claims": {"claims": ["26 days"]}})
    await _judge("correctness", first_llm, cache=cache).evaluate(_sample())

    second_llm = ScriptedJudgeLlm(
        {"extract_reference_claims": AssertionError("gold must come from the cache")}
    )
    result = await _judge("correctness", second_llm, cache=cache).evaluate(
        _sample(actual_output="A different candidate answer")
    )
    assert result.metadata["cache_hit"] is True
    assert second_llm.steps() == ["verify_reference_coverage"]
    assert "[C1] 26 days" in second_llm.calls[0]["user"]


class _RacingCache(InMemoryJudgeClaimCache):
    """Misses on the first get; another writer stores its claims just before our put."""

    def __init__(self, other_claims: list[str]) -> None:
        super().__init__()
        self._other_claims = other_claims
        self._gets = 0

    async def get(self, key: str) -> list[str] | None:
        self._gets += 1
        return None if self._gets == 1 else await super().get(key)

    async def put(self, key: str, *, prompt_version: str, model: str, claims: list[str]) -> None:
        await super().put(
            key, prompt_version=prompt_version, model=model, claims=self._other_claims
        )
        await super().put(key, prompt_version=prompt_version, model=model, claims=claims)


@pytest.mark.asyncio
async def test_correctness_scores_against_stored_claims_after_concurrent_write() -> None:
    cache = _RacingCache(["other gold claim"])
    llm = ScriptedJudgeLlm({"extract_reference_claims": {"claims": ["my own claim"]}})
    result = await _judge("correctness", llm, cache=cache).evaluate(_sample())

    coverage_prompts = [c["user"] for c in llm.calls if c["step"] == "verify_reference_coverage"]
    assert len(coverage_prompts) == 1
    assert "other gold claim" in coverage_prompts[0]
    assert "my own claim" not in coverage_prompts[0]
    assert result.metadata["n_gold"] == 1
    assert [c["text"] for c in result.metadata["claims"]] == ["other gold claim"]
    assert result.metadata["cache_hit"] is False


@pytest.mark.asyncio
async def test_correctness_invalid_extract_is_not_cached() -> None:
    cache = InMemoryJudgeClaimCache()
    bad = ScriptedJudgeLlm({"extract_reference_claims": ["nope", "nope"]})
    result = await _judge("correctness", bad, cache=cache).evaluate(_sample())
    assert result.label == "ERROR"

    good = ScriptedJudgeLlm()
    result = await _judge("correctness", good, cache=cache).evaluate(_sample())
    assert result.metadata["cache_hit"] is False


@pytest.mark.asyncio
async def test_correctness_skips_without_expected_or_gold_claims() -> None:
    llm = ScriptedJudgeLlm({"extract_reference_claims": {"claims": []}})
    judge = _judge("correctness", llm)
    assert (await judge.evaluate(_sample(expected_output=None))).label == "SKIPPED"
    no_gold = await judge.evaluate(_sample())
    assert no_gold.label == "SKIPPED"
    assert no_gold.explanation.startswith("no_gold_claims")


@pytest.mark.asyncio
@pytest.mark.parametrize("config", [{}, {"scoring": "f1"}])
async def test_correctness_never_sees_documents_or_gold_doc_ids(config: dict[str, Any]) -> None:
    llm = ScriptedJudgeLlm()
    result = await _judge("correctness", llm, config).evaluate(_sample())
    assert result.label != "ERROR"
    assert llm.calls
    for call in llm.calls:
        assert "Full-time staff" not in call["user"]
        assert "GOLD-DOC" not in call["user"]


# --- answer relevance ------------------------------------------------------------


@pytest.mark.asyncio
async def test_answer_relevance_rubric_never_sees_gold_or_documents() -> None:
    llm = ScriptedJudgeLlm({"rubric_answer_relevance": {"reasoning": "on topic", "level": 5}})
    result = await _judge("answer_relevance", llm).evaluate(
        _sample(expected_output="GOLD-ANSWER-TEXT")
    )
    assert result.score == 1.0
    user = llm.calls[0]["user"]
    assert "GOLD-ANSWER-TEXT" not in user
    assert "Full-time staff" not in user
    assert "GOLD-DOC" not in user


# --- errors ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_output_after_repair_is_error_with_raw_output() -> None:
    llm = ScriptedJudgeLlm({"rubric_answer_relevance": ["garbage", "x" * 5000]})
    result = await _judge("answer_relevance", llm).evaluate(_sample())
    assert result.label == "ERROR"
    assert result.score is None
    assert result.metadata["error_type"] == "judge_output_invalid"
    assert len(result.metadata["raw_output"]) == 2000
    assert result.metadata["method"] == "rubric"


@pytest.mark.asyncio
async def test_provider_failure_is_classified_error() -> None:
    llm = ScriptedJudgeLlm({"rubric_answer_relevance": TimeoutError("slow provider")})
    result = await _judge("answer_relevance", llm).evaluate(_sample())
    assert result.label == "ERROR"
    assert result.metadata["error_type"] == "llm_unavailable"
    assert "slow provider" in result.explanation


# --- review fixes ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_claim_explanations_are_capped() -> None:
    long_claims = [f"{i}" + "x" * 999 for i in range(5)]
    llm = ScriptedJudgeLlm(
        {
            "extract_answer_claims": {"claims": long_claims},
            "verify_against_documents": {
                "verdicts": [{"reasoning": "r", "verdict": "not_supported"}] * 5
            },
        }
    )
    result = await _judge("groundedness", llm).evaluate(_sample())
    assert len(result.explanation) <= 1000
    assert result.explanation.startswith("0/5 claims supported")
    assert "…" in result.explanation

    llm = ScriptedJudgeLlm(
        {
            "extract_reference_claims": {"claims": long_claims},
            "verify_reference_coverage": _coverage(*["missing"] * 5),
        }
    )
    result = await _judge("correctness", llm, {"scoring": "f1"}).evaluate(_sample())
    assert len(result.explanation) <= 1000
    assert result.explanation.startswith("0/5 reference facts covered")


@pytest.mark.parametrize("bad", [True, float("nan"), float("inf"), "warm", "nan"])
def test_invalid_temperature_raises(bad: Any) -> None:
    with pytest.raises(ValueError, match="temperature"):
        _judge("answer_relevance", ScriptedJudgeLlm(), {"temperature": bad})


@pytest.mark.asyncio
async def test_numeric_string_temperature_and_model_strip() -> None:
    llm = ScriptedJudgeLlm()
    await _judge("answer_relevance", llm, {"temperature": "0.2", "model": "  m1 "}).evaluate(
        _sample()
    )
    assert llm.calls[0]["temperature"] == 0.2
    assert llm.calls[0]["model"] == "m1"

    llm = ScriptedJudgeLlm()
    await _judge("answer_relevance", llm, {"model": "   "}).evaluate(_sample())
    assert llm.calls[0]["model"] == "judge-default"


@pytest.mark.asyncio
async def test_precheck_results_carry_judge_metadata() -> None:
    judge = _judge("groundedness", ScriptedJudgeLlm())
    skipped = await judge.evaluate(_sample(context=None))
    assert skipped.metadata["prompt_version"] == "groundedness.claims.v3"
    failed = await judge.evaluate(_sample(context={"documents": []}))
    assert failed.metadata["method"] == "claims"
    missing = await _judge("correctness", ScriptedJudgeLlm()).evaluate(
        _sample(expected_output=None)
    )
    assert missing.metadata["judge_kind"] == "correctness"


@pytest.mark.asyncio
async def test_correctness_f1_answer_without_claims_is_explained() -> None:
    llm = ScriptedJudgeLlm(
        {
            "extract_reference_claims": {"claims": ["26 days"]},
            "extract_answer_claims": {"claims": []},
        }
    )
    result = await _judge("correctness", llm, {"scoring": "f1"}).evaluate(_sample())
    assert result.score == 0.0
    assert result.metadata["precision"] == 0.0
    assert "answer has no claims" in result.explanation


@pytest.mark.asyncio
async def test_correctness_f1_answer_contradiction_scores_zero() -> None:
    llm = ScriptedJudgeLlm(
        {
            "extract_reference_claims": {"claims": ["26 days", "via the portal"]},
            "verify_reference_coverage": _coverage("covered", "covered"),
            "extract_answer_claims": {"claims": ["26 days", "requests go by fax"]},
            "verify_against_reference": {
                "verdicts": [
                    {"reasoning": "r", "verdict": "supported"},
                    {"reasoning": "r", "verdict": "contradicted"},
                ]
            },
        }
    )
    result = await _judge("correctness", llm, {"scoring": "f1"}).evaluate(_sample())
    assert result.metadata["n_contradicted"] == 0
    assert result.metadata["recall"] == 1.0
    assert result.score == 0.0


# --- context_precision -----------------------------------------------------------


@pytest.mark.asyncio
async def test_context_precision_claims_average_precision() -> None:
    docs = {
        "documents": [
            {"id": "kb-1", "text": "Full-time staff get 26 days of PTO."},
            {"id": "kb-2", "text": "The cafeteria menu changes weekly."},
            {"id": "kb-3", "text": "PTO is requested via the portal."},
        ]
    }
    llm = ScriptedJudgeLlm(
        {
            "verify_context_relevance": {
                "verdicts": [
                    {"reasoning": "r", "verdict": "relevant"},
                    {"reasoning": "r", "verdict": "not_relevant"},
                    {"reasoning": "r", "verdict": "relevant"},
                ]
            }
        }
    )
    result = await _judge("context_precision", llm).evaluate(_sample(context=docs))
    assert result.score == pytest.approx(5 / 6)
    assert result.label is None
    assert result.metadata["prompt_version"] == "context_precision.claims.v3"
    assert result.metadata["n_documents"] == 3
    assert result.metadata["n_relevant"] == 2
    assert result.metadata["documents"][1]["verdict"] == "not_relevant"
    assert llm.steps() == ["verify_context_relevance"]
    assert "REFERENCE ANSWER" in llm.calls[0]["user"]
    assert "26 days, requested via the portal." in llm.calls[0]["user"]


@pytest.mark.asyncio
async def test_context_precision_all_irrelevant_is_zero() -> None:
    llm = ScriptedJudgeLlm(
        {"verify_context_relevance": {"verdicts": [{"reasoning": "r", "verdict": "not_relevant"}]}}
    )
    result = await _judge("context_precision", llm).evaluate(_sample())
    assert result.score == 0.0
    assert result.metadata["n_relevant"] == 0


@pytest.mark.asyncio
async def test_context_precision_prechecks_do_not_call_llm() -> None:
    llm = ScriptedJudgeLlm()
    judge = _judge("context_precision", llm)
    assert (await judge.evaluate(_sample(expected_output=None))).label == "SKIPPED"
    assert (await judge.evaluate(_sample(context=None))).label == "SKIPPED"
    empty = await judge.evaluate(_sample(context={"documents": []}))
    assert (empty.label, empty.score) == ("FAIL", 0.0)
    assert (await judge.evaluate(_sample(actual_output=None))).label == "SKIPPED"
    assert llm.calls == []


@pytest.mark.asyncio
async def test_context_precision_rubric_method() -> None:
    llm = ScriptedJudgeLlm({"rubric_context_precision": {"reasoning": "noisy", "level": 3}})
    result = await _judge("context_precision", llm, {"method": "rubric"}).evaluate(_sample())
    assert result.score == 0.5
    assert result.metadata["prompt_version"] == "context_precision.rubric.v3"
    assert llm.steps() == ["rubric_context_precision"]


@pytest.mark.asyncio
async def test_context_precision_k_truncates_documents() -> None:
    docs = {
        "documents": [
            {"id": "a", "text": "useful"},
            {"id": "b", "text": "noise"},
            {"id": "c", "text": "more"},
        ]
    }
    llm = ScriptedJudgeLlm()
    result = await _judge("context_precision", llm, {"k": 2}).evaluate(_sample(context=docs))
    assert result.metadata["n_documents"] == 2
    assert result.metadata["documents_truncated"] is True
    assert "[D3]" not in llm.calls[0]["user"]


# --- context_recall --------------------------------------------------------------


@pytest.mark.asyncio
async def test_context_recall_claims_scores_covered_ratio() -> None:
    llm = ScriptedJudgeLlm(
        {
            "extract_reference_claims": {"claims": ["26 days", "via the portal"]},
            "verify_context_coverage": _coverage("covered", "missing"),
        }
    )
    result = await _judge("context_recall", llm).evaluate(_sample())
    assert result.score == 0.5
    assert result.label is None
    assert result.explanation == '1/2 reference facts in context; missing: "via the portal"'
    meta = result.metadata
    assert meta["prompt_version"] == "context_recall.claims.v3"
    assert (meta["n_gold"], meta["n_covered"], meta["n_missing"]) == (2, 1, 1)
    assert meta["recall"] == 0.5
    assert meta["cache_hit"] is False
    assert llm.steps() == ["extract_reference_claims", "verify_context_coverage"]
    assert "Full-time staff" in llm.calls[1]["user"]
    assert "You get 26 days" not in llm.calls[1]["user"]


@pytest.mark.asyncio
async def test_context_recall_contradiction_does_not_zero_score() -> None:
    llm = ScriptedJudgeLlm(
        {
            "extract_reference_claims": {"claims": ["26 days", "via the portal"]},
            "verify_context_coverage": _coverage("contradicted", "covered"),
        }
    )
    result = await _judge("context_recall", llm).evaluate(_sample())
    assert result.score == 0.5
    assert result.metadata["n_contradicted"] == 1
    assert "contradicted:" in (result.explanation or "")


@pytest.mark.asyncio
async def test_context_recall_reuses_cached_gold_claims() -> None:
    cache = InMemoryJudgeClaimCache()
    first_llm = ScriptedJudgeLlm({"extract_reference_claims": {"claims": ["26 days"]}})
    await _judge("context_recall", first_llm, cache=cache).evaluate(_sample())

    second_llm = ScriptedJudgeLlm(
        {"extract_reference_claims": AssertionError("gold must come from the cache")}
    )
    result = await _judge("context_recall", second_llm, cache=cache).evaluate(
        _sample(actual_output="A different candidate answer")
    )
    assert result.metadata["cache_hit"] is True
    assert second_llm.steps() == ["verify_context_coverage"]


@pytest.mark.asyncio
async def test_context_recall_prechecks_do_not_call_llm() -> None:
    llm = ScriptedJudgeLlm()
    judge = _judge("context_recall", llm)
    assert (await judge.evaluate(_sample(expected_output=None))).label == "SKIPPED"
    assert (await judge.evaluate(_sample(context=None))).label == "SKIPPED"
    empty = await judge.evaluate(_sample(context={"documents": []}))
    assert (empty.label, empty.score) == ("FAIL", 0.0)
    assert (await judge.evaluate(_sample(actual_output=None))).label == "SKIPPED"
    assert llm.calls == []


@pytest.mark.asyncio
async def test_context_recall_skips_without_gold_claims() -> None:
    llm = ScriptedJudgeLlm({"extract_reference_claims": {"claims": []}})
    result = await _judge("context_recall", llm).evaluate(_sample())
    assert result.label == "SKIPPED"
    assert result.explanation is not None and result.explanation.startswith("no_gold_claims")


@pytest.mark.asyncio
async def test_context_recall_rubric_method() -> None:
    llm = ScriptedJudgeLlm({"rubric_context_recall": {"reasoning": "partial", "level": 3}})
    result = await _judge("context_recall", llm, {"method": "rubric"}).evaluate(_sample())
    assert result.score == 0.5
    assert result.metadata["prompt_version"] == "context_recall.rubric.v3"
    assert llm.steps() == ["rubric_context_recall"]


@pytest.mark.asyncio
async def test_bootstrap_registers_new_judges() -> None:
    clear_registry()
    llm = ScriptedJudgeLlm()
    bootstrap_evaluators(llm, default_model="judge-default")
    try:
        judge = create_evaluator("groundedness", {"kind": "groundedness"})
        assert judge.prompt_version == "groundedness.claims.v3"
        result = await judge.evaluate(_sample())
        assert result.metadata["model"] == "judge-default"
        cp = create_evaluator("context_precision", {"kind": "context_precision"})
        assert cp.prompt_version == "context_precision.claims.v3"
        cr = create_evaluator("context_recall", {"kind": "context_recall"})
        assert cr.prompt_version == "context_recall.claims.v3"
    finally:
        clear_registry()
