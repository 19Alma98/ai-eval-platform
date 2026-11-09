from __future__ import annotations

import re
from typing import Any

import pytest

from opengrade_server.evaluation import bootstrap_evaluators
from opengrade_server.evaluation.judges import prompts
from opengrade_server.evaluation.judges.evaluators import (
    JUDGE_KINDS,
    JudgeDefaults,
    create_llm_judge,
)
from opengrade_server.evaluation.judges.rag_checks import (
    DEFAULT_CITATION_PATTERN,
    label_answerable,
    looks_like_refusal,
    split_cited_segments,
)
from opengrade_server.evaluation.protocol import EvaluationSample
from opengrade_server.evaluation.registry import clear_registry, create_evaluator
from support.fake_llm import ScriptedJudgeLlm, claim_count

_DEFAULTS = JudgeDefaults(model="judge-default")
_PATTERN = re.compile(DEFAULT_CITATION_PATTERN)
_DOCS = [
    {"id": "pto", "title": "PTO policy", "text": "Full-time staff get 20 PTO days per year."},
    {"id": "parking", "text": "Parking downtown costs 5 EUR per day."},
]


def _sample(**overrides: Any) -> EvaluationSample:
    values: dict[str, Any] = {
        "input": "How many PTO days do I get?",
        "expected_output": None,
        "actual_output": "You get 20 PTO days per year [pto].",
        "context": {"documents": _DOCS},
        "metadata": {},
    }
    values.update(overrides)
    return EvaluationSample(**values)


def _judge(kind: str, llm: ScriptedJudgeLlm, config: dict[str, Any] | None = None):
    return create_llm_judge(kind, config or {}, llm, defaults=_DEFAULTS)


def _verdicts(*labels: str):
    def reply(user: str) -> dict[str, Any]:
        assert claim_count(user) == len(labels)
        return {
            "verdicts": [
                {"reasoning": "r", "verdict": v, "doc_ids": [], "quote": None} for v in labels
            ]
        }

    return reply


# --- citation parsing ------------------------------------------------------------------


def test_split_attaches_trailing_citations_to_previous_sentence() -> None:
    segments = split_cited_segments(
        "You get 20 days. [pto] Parking is paid [parking, pto]. Hope this helps!", _PATTERN
    )
    assert [(s.text, s.citations) for s in segments] == [
        ("You get 20 days.", ("pto",)),
        ("Parking is paid.", ("parking", "pto")),
        ("Hope this helps!", ()),
    ]


def test_split_ignores_reference_list_links_and_bullets() -> None:
    answer = (
        "- You get 20 days [1].\n"
        "- See [the portal](https://hr.example) for details.\n"
        "\n**Sources:**\n[1] PTO policy\n[2] Parking"
    )
    segments = split_cited_segments(answer, _PATTERN)
    assert [(s.text, s.citations) for s in segments] == [
        ("You get 20 days.", ("1",)),
        ("See [the portal](https://hr.example) for details.", ()),
    ]


def test_split_footnote_and_doc_prefix_markers() -> None:
    segments = split_cited_segments("20 days[^pto] and paid parking [doc:parking].", _PATTERN)
    assert segments[0].citations == ("pto", "parking")


# --- citation accuracy ------------------------------------------------------------------


async def test_citation_accuracy_verifies_each_statement_against_cited_docs_only() -> None:
    llm = ScriptedJudgeLlm({"verify_citations": _verdicts("supported", "not_supported")})
    result = await _judge("citation_accuracy", llm).evaluate(
        _sample(actual_output="You get 20 PTO days [pto]. Parking is free [pto].")
    )
    assert result.score == 0.5
    assert result.label is None
    assert "1/2 cited statements supported" in result.explanation
    assert llm.steps() == ["verify_citations"]
    user = llm.calls[0]["user"]
    assert "(cites: pto)" in user
    assert "Parking downtown" not in user  # uncited documents are not shown to the judge
    claims = result.metadata["claims"]
    assert [c["verdict"] for c in claims] == ["supported", "not_supported"]
    assert claims[0]["doc_ids"] == ["pto"]
    assert result.metadata["n_statements"] == 2
    assert result.metadata["citation_coverage"] == 1.0


async def test_citation_accuracy_numeric_and_title_citations_resolve() -> None:
    llm = ScriptedJudgeLlm()
    result = await _judge("citation_accuracy", llm).evaluate(
        _sample(actual_output="You get 20 days [1]. Parking costs 5 EUR [PTO policy; 2].")
    )
    assert result.score == 1.0
    assert [c["doc_ids"] for c in result.metadata["claims"]] == [["pto"], ["pto", "parking"]]


async def test_citation_to_unretrieved_source_fails_without_llm_call() -> None:
    llm = ScriptedJudgeLlm()
    result = await _judge("citation_accuracy", llm).evaluate(
        _sample(actual_output="You get 20 days [handbook].")
    )
    assert result.score == 0.0
    assert llm.calls == []
    claim = result.metadata["claims"][0]
    assert claim["verdict"] == "invalid_citation"
    assert claim["invalid_citations"] == ["handbook"]
    assert result.metadata["n_invalid_citations"] == 1
    assert "invalid citation" in result.explanation


async def test_mixed_valid_and_invalid_citations_count_as_invalid() -> None:
    llm = ScriptedJudgeLlm()
    result = await _judge("citation_accuracy", llm).evaluate(
        _sample(actual_output="You get 20 days [pto, ghost].")
    )
    assert result.score == 0.0
    assert result.metadata["claims"][0]["verdict"] == "invalid_citation"


async def test_no_citations_fails_unless_refusal_or_not_required() -> None:
    llm = ScriptedJudgeLlm()
    result = await _judge("citation_accuracy", llm).evaluate(
        _sample(actual_output="You get 20 days.")
    )
    assert result.label == "FAIL"
    assert result.score == 0.0
    refusal = await _judge("citation_accuracy", llm).evaluate(
        _sample(actual_output="I don't know, the documents do not say.")
    )
    assert refusal.label == "SKIPPED"
    optional = await _judge("citation_accuracy", llm, {"require_citations": False}).evaluate(
        _sample(actual_output="You get 20 days.")
    )
    assert optional.label == "SKIPPED"
    assert llm.calls == []


async def test_min_coverage_fails_answers_with_uncited_sentences() -> None:
    llm = ScriptedJudgeLlm()
    judge = _judge("citation_accuracy", llm, {"min_coverage": 0.75})
    result = await judge.evaluate(
        _sample(actual_output="You get 20 days [pto]. Parking is 5 EUR a day.")
    )
    assert result.score == 1.0
    assert result.label == "FAIL"
    assert result.metadata["citation_coverage"] == 0.5
    assert "citation coverage 50% < 75%" in result.explanation


async def test_custom_pattern_and_redacted_documents() -> None:
    llm = ScriptedJudgeLlm()
    judge = _judge("citation_accuracy", llm, {"pattern": r"\(source: ([^)]+)\)"})
    result = await judge.evaluate(_sample(actual_output="You get 20 days (source: pto)."))
    assert result.score == 1.0
    assert result.metadata["pattern"] == r"\(source: ([^)]+)\)"
    redacted = await _judge("citation_accuracy", llm).evaluate(
        _sample(context={"documents": [{"id": "pto"}]})
    )
    assert redacted.label == "SKIPPED"
    assert "no text" in redacted.explanation


def test_citation_config_validation() -> None:
    llm = ScriptedJudgeLlm()
    with pytest.raises(ValueError, match="pattern"):
        _judge("citation_accuracy", llm, {"pattern": "[unclosed"})
    with pytest.raises(ValueError, match="min_coverage"):
        _judge("citation_accuracy", llm, {"min_coverage": 2})
    with pytest.raises(ValueError, match="require_citations"):
        _judge("citation_accuracy", llm, {"require_citations": "yes"})
    with pytest.raises(ValueError, match="method"):
        _judge("citation_accuracy", llm, {"method": "rubric"})


# --- refusal ------------------------------------------------------------------------------


def _refusal_reply(**fields: Any) -> dict[str, Any]:
    return {
        "reasoning": "r",
        "answer_refused": False,
        "reference_refused": None,
        "answerable_from_documents": None,
        **fields,
    }


@pytest.mark.parametrize(
    ("answerable", "refused", "outcome", "score"),
    [
        (True, False, "correct_answer", 1.0),
        (True, True, "over_refusal", 0.0),
        (False, True, "correct_refusal", 1.0),
        (False, False, "missed_refusal", 0.0),
    ],
)
async def test_refusal_outcomes_from_dataset_label(
    answerable: bool, refused: bool, outcome: str, score: float
) -> None:
    llm = ScriptedJudgeLlm({"classify_refusal": _refusal_reply(answer_refused=refused)})
    result = await _judge("refusal", llm).evaluate(
        _sample(metadata={"answerable": answerable}, expected_output="ignored when labelled")
    )
    assert result.score == score
    assert result.label == ("PASS" if score else "FAIL")
    assert result.metadata["outcome"] == outcome
    assert result.metadata["answerable_source"] == "label"
    assert "REFERENCE ANSWER" not in llm.calls[0]["user"]
    assert "DOCUMENTS" not in llm.calls[0]["user"]


async def test_refusal_label_variants() -> None:
    assert label_answerable({"answerable": "false"}) is False
    assert label_answerable({"expected_refusal": True}) is False
    assert label_answerable({"should_refuse": "no"}) is True
    assert label_answerable({"answerable": "maybe"}) is None


async def test_refusal_reads_reference_answer_without_label() -> None:
    llm = ScriptedJudgeLlm(
        {"classify_refusal": _refusal_reply(answer_refused=False, reference_refused=True)}
    )
    result = await _judge("refusal", llm).evaluate(
        _sample(expected_output="The documents do not cover parking for contractors.")
    )
    assert result.metadata["outcome"] == "missed_refusal"
    assert result.metadata["answerable_source"] == "reference"
    assert "REFERENCE ANSWER" in llm.calls[0]["user"]


async def test_refusal_goldless_uses_documents() -> None:
    llm = ScriptedJudgeLlm(
        {"classify_refusal": _refusal_reply(answer_refused=True, answerable_from_documents=True)}
    )
    result = await _judge("refusal", llm).evaluate(_sample(actual_output="I can't help with that."))
    assert result.metadata["outcome"] == "over_refusal"
    assert result.metadata["answerable_source"] == "documents"
    assert "DOCUMENTS" in llm.calls[0]["user"]


async def test_refusal_no_documents_means_should_refuse() -> None:
    llm = ScriptedJudgeLlm({"classify_refusal": _refusal_reply(answer_refused=False)})
    result = await _judge("refusal", llm).evaluate(_sample(context={"documents": []}))
    assert result.metadata["outcome"] == "missed_refusal"
    assert "DOCUMENTS" not in llm.calls[0]["user"]


async def test_refusal_missing_field_triggers_format_repair() -> None:
    llm = ScriptedJudgeLlm(
        {
            "classify_refusal": [
                _refusal_reply(answer_refused=True),  # answerable_from_documents missing
                _refusal_reply(answer_refused=True, answerable_from_documents=False),
            ]
        }
    )
    result = await _judge("refusal", llm).evaluate(_sample())
    assert result.metadata["outcome"] == "correct_refusal"
    assert result.metadata["llm_calls"] == 2


async def test_refusal_skips_without_any_answerability_source() -> None:
    llm = ScriptedJudgeLlm()
    result = await _judge("refusal", llm).evaluate(_sample(context=None))
    assert result.label == "SKIPPED"
    labelled_only = await _judge("refusal", llm, {"answerable_from": "label"}).evaluate(_sample())
    assert labelled_only.label == "SKIPPED"
    assert llm.calls == []


async def test_refusal_check_filters_items() -> None:
    llm = ScriptedJudgeLlm()
    only_unanswerable = _judge("refusal", llm, {"check": "unanswerable"})
    skipped = await only_unanswerable.evaluate(_sample(metadata={"answerable": True}))
    assert skipped.label == "SKIPPED"
    assert llm.calls == []


async def test_refusal_phrases_method_is_deterministic() -> None:
    llm = ScriptedJudgeLlm()
    judge = _judge("refusal", llm, {"method": "phrases"})
    correct = await judge.evaluate(
        _sample(
            actual_output="Mi dispiace, non ho informazioni su questo.",
            expected_output="Non lo so: i documenti non ne parlano.",
        )
    )
    assert correct.metadata["outcome"] == "correct_refusal"
    over = await judge.evaluate(
        _sample(actual_output="I don't know.", metadata={"answerable": True})
    )
    assert over.metadata["outcome"] == "over_refusal"
    no_source = await judge.evaluate(_sample())  # documents only: phrases cannot read them
    assert no_source.label == "SKIPPED"
    assert llm.calls == []
    custom = _judge("refusal", llm, {"method": "phrases", "refusal_phrases": ["ask HR"]})
    result = await custom.evaluate(
        _sample(actual_output="Please ask HR.", metadata={"answerable": False})
    )
    assert result.metadata["outcome"] == "correct_refusal"


def test_refusal_phrases_match_whole_words() -> None:
    assert looks_like_refusal("Non so rispondere")
    assert not looks_like_refusal("Non sono sicuro che 20 giorni bastino")  # "non so" ⊂ "non sono"
    assert looks_like_refusal("I don’t know")  # typographic apostrophe


def test_refusal_config_validation() -> None:
    llm = ScriptedJudgeLlm()
    with pytest.raises(ValueError, match="answerable_from"):
        _judge("refusal", llm, {"answerable_from": "magic"})
    with pytest.raises(ValueError, match="check"):
        _judge("refusal", llm, {"check": "all"})
    with pytest.raises(ValueError, match="classify"):
        _judge("refusal", llm, {"method": "phrases", "answerable_from": "documents"})
    with pytest.raises(ValueError, match="refusal_phrases"):
        _judge("refusal", llm, {"refusal_phrases": []})


# --- registry / prompts --------------------------------------------------------------------


def test_new_kinds_registered_and_versioned() -> None:
    assert {
        "citation_accuracy",
        "refusal",
        "query_rewrite_faithfulness",
        "conversation_consistency",
        "resolution",
    } <= set(JUDGE_KINDS)
    clear_registry()
    try:
        bootstrap_evaluators(ScriptedJudgeLlm(), default_model="m")
        assert create_evaluator("citation_accuracy", {}).name == "citation_accuracy"
        assert create_evaluator("refusal", {"method": "phrases"}).name == "refusal"
    finally:
        clear_registry()
    assert prompts.prompt_version("refusal", "classify") != prompts.prompt_version(
        "refusal", "phrases"
    )
    assert prompts.prompt_version("citation_accuracy", "claims").startswith(
        "citation_accuracy.claims."
    )
