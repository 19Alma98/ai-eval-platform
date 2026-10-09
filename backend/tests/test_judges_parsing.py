from __future__ import annotations

from typing import Literal

import pytest
from pydantic import BaseModel

from aiobs_server.evaluation.judges.errors import (
    CONTEXT_OVERFLOW,
    LLM_ERROR,
    LLM_UNAVAILABLE,
    JudgeOutputError,
    classify_llm_error,
)
from aiobs_server.evaluation.judges.parsing import CallOptions, call_structured, extract_json_object
from aiobs_server.evaluation.judges.schemas import (
    CoverageVerifyOut,
    ExtractOut,
    RubricOut,
    SupportVerifyOut,
)
from support.fake_llm import ScriptedJudgeLlm


def test_plain_json() -> None:
    assert extract_json_object('{"level": 4}') == {"level": 4}


def test_code_fence() -> None:
    text = 'Here you go:\n```json\n{"claims": ["a"]}\n```\nThanks'
    assert extract_json_object(text) == {"claims": ["a"]}


def test_object_wrapped_in_prose() -> None:
    text = 'Sure! {"level": 3, "reasoning": "partial"} Hope this helps.'
    assert extract_json_object(text) == {"level": 3, "reasoning": "partial"}


def test_braces_inside_strings_do_not_break_matching() -> None:
    text = 'Answer: {"reasoning": "uses {curly} and \\"quotes\\"", "level": 5} done'
    assert extract_json_object(text)["level"] == 5


def test_skips_invalid_candidate_and_finds_next_object() -> None:
    text = '{not json} then {"level": 2}'
    assert extract_json_object(text) == {"level": 2}


@pytest.mark.parametrize("text", ["", "   ", "no json here", "[1, 2]", '"just a string"'])
def test_rejects_non_objects(text: str) -> None:
    with pytest.raises(ValueError):
        extract_json_object(text)


def test_invalid_fence_falls_back_to_object_outside_it() -> None:
    text = '```\nuse {x} here\n```\n{"level": 2}'
    assert extract_json_object(text) == {"level": 2}


def test_bare_fence_without_json_tag() -> None:
    text = 'Result:\n```\n{"level": 1}\n```'
    assert extract_json_object(text) == {"level": 1}


_OPTS = CallOptions(model="judge-m", temperature=None)
_SYSTEM = "STEP: rubric_test\nRate it."


class _Pick(BaseModel):
    choice: Literal["a", "b"]


@pytest.mark.asyncio
async def test_call_structured_first_try() -> None:
    llm = ScriptedJudgeLlm({"rubric_test": {"choice": "a"}})
    result = await call_structured(llm, system=_SYSTEM, user="u", schema=_Pick, options=_OPTS)
    assert result.value.choice == "a"
    assert result.calls == 1
    assert llm.calls[0]["model"] == "judge-m"


@pytest.mark.asyncio
async def test_call_structured_repairs_once_with_validation_error() -> None:
    llm = ScriptedJudgeLlm({"rubric_test": [{"choice": "zzz"}, {"choice": "b"}]})
    result = await call_structured(llm, system=_SYSTEM, user="u", schema=_Pick, options=_OPTS)
    assert result.value.choice == "b"
    assert result.calls == 2
    history = llm.calls[1]["history"]
    assert history[0] == {"role": "assistant", "content": '{"choice": "zzz"}'}
    assert history[1]["role"] == "user"
    assert "choice" in history[1]["content"]


@pytest.mark.asyncio
async def test_call_structured_raises_after_second_failure() -> None:
    llm = ScriptedJudgeLlm({"rubric_test": ["not json", "still not json"]})
    with pytest.raises(JudgeOutputError) as exc_info:
        await call_structured(llm, system=_SYSTEM, user="u", schema=_Pick, options=_OPTS)
    assert exc_info.value.raw == "still not json"
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_call_structured_check_failure_triggers_repair() -> None:
    def check(value: _Pick) -> None:
        if value.choice != "b":
            raise ValueError("must pick b")

    llm = ScriptedJudgeLlm({"rubric_test": [{"choice": "a"}, {"choice": "b"}]})
    result = await call_structured(
        llm, system=_SYSTEM, user="u", schema=_Pick, options=_OPTS, check=check
    )
    assert result.calls == 2
    assert "must pick b" in llm.calls[1]["history"][1]["content"]


def test_schemas_normalize_lenient_model_output() -> None:
    support = SupportVerifyOut.model_validate(
        {"verdicts": [{"verdict": " Not Supported ", "doc_ids": [12, "kb-1"], "reasoning": None}]}
    )
    assert support.verdicts[0].verdict == "not_supported"
    assert support.verdicts[0].doc_ids == ["12", "kb-1"]
    coverage = CoverageVerifyOut.model_validate({"verdicts": [{"verdict": "COVERED"}]})
    assert coverage.verdicts[0].verdict == "covered"
    assert RubricOut.model_validate({"level": "4"}).level == 4


def test_rubric_level_out_of_range_is_rejected() -> None:
    with pytest.raises(ValueError):
        RubricOut.model_validate({"level": 7})


def test_classify_llm_error() -> None:
    from litellm import exceptions as llm_exc

    def bare(cls: type[BaseException]) -> BaseException:
        # Constructor signatures differ across LiteLLM versions; isinstance is all we need.
        return cls.__new__(cls)

    assert classify_llm_error(bare(llm_exc.ContextWindowExceededError)) == CONTEXT_OVERFLOW
    assert classify_llm_error(bare(llm_exc.Timeout)) == LLM_UNAVAILABLE
    assert classify_llm_error(bare(llm_exc.RateLimitError)) == LLM_UNAVAILABLE
    assert classify_llm_error(bare(llm_exc.APIConnectionError)) == LLM_UNAVAILABLE
    assert classify_llm_error(TimeoutError()) == LLM_UNAVAILABLE
    assert classify_llm_error(RuntimeError("boom")) == LLM_ERROR


def test_extract_claims_unwraps_single_string_dict() -> None:
    out = ExtractOut.model_validate(
        {"claims": [{"claim": " x "}, " y ", "", "  ", None, {"a": " "}]}
    )
    assert out.claims == ["x", "y"]


@pytest.mark.parametrize(
    "claims",
    [[1, 2], [["a"]], [{"a": "x", "b": "y"}], [{"a": 1}]],
)
def test_extract_claims_rejects_other_item_types(claims: object) -> None:
    with pytest.raises(ValueError):
        ExtractOut.model_validate({"claims": claims})


def test_verdict_normalization_collapses_separators_and_punctuation() -> None:
    support = SupportVerifyOut.model_validate(
        {"verdicts": [{"verdict": "Not  supported"}, {"verdict": "supported."}]}
    )
    assert [v.verdict for v in support.verdicts] == ["not_supported", "supported"]
    coverage = CoverageVerifyOut.model_validate({"verdicts": [{"verdict": "Covered:"}]})
    assert coverage.verdicts[0].verdict == "covered"


def test_doc_ids_bare_value_becomes_list() -> None:
    support = SupportVerifyOut.model_validate(
        {
            "verdicts": [
                {"verdict": "supported", "doc_ids": "kb-1"},
                {"verdict": "supported", "doc_ids": 7},
            ]
        }
    )
    assert support.verdicts[0].doc_ids == ["kb-1"]
    assert support.verdicts[1].doc_ids == ["7"]


@pytest.mark.asyncio
async def test_call_structured_empty_first_reply_uses_placeholder_in_history() -> None:
    llm = ScriptedJudgeLlm({"rubric_test": ["  ", {"choice": "a"}]})
    result = await call_structured(llm, system=_SYSTEM, user="u", schema=_Pick, options=_OPTS)
    assert result.calls == 2
    assert llm.calls[1]["history"][0] == {"role": "assistant", "content": "(empty reply)"}
