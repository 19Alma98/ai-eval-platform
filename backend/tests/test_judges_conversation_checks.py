from __future__ import annotations

from typing import Any

import pytest

from opengrade_server.evaluation.judges import prompts
from opengrade_server.evaluation.judges.evaluators import JudgeDefaults, create_llm_judge
from opengrade_server.evaluation.protocol import EvaluationSample
from support.fake_llm import ScriptedJudgeLlm

_DEFAULTS = JudgeDefaults(model="judge-default")

_CONVERSATION_CONSISTENCY_SKIP = (
    "fewer than two assistant turns; consistency is only scored on multi-turn dialogs"
)


def _judge(kind: str, llm: ScriptedJudgeLlm, config: dict[str, Any] | None = None):
    return create_llm_judge(kind, config or {}, llm, defaults=_DEFAULTS)


def _chat_sample(**overrides: Any) -> EvaluationSample:
    values: dict[str, Any] = {
        "input": {
            "history": [
                {"role": "user", "content": "What is the Pro plan price?"},
                {"role": "assistant", "content": "Pro costs $49/month."},
                {"role": "user", "content": "And the Team plan?"},
                {
                    "role": "assistant",
                    "content": "Team is $29/month. Pro is actually $99/month.",
                },
            ],
            "question": "Thanks — confirm Pro once more?",
        },
        "expected_output": None,
        "actual_output": "Pro costs $49/month.",
        "context": None,
        "metadata": {},
    }
    values.update(overrides)
    return EvaluationSample(**values)


def test_optional_history_text_none_for_string_question() -> None:
    assert prompts.optional_history_text("How many PTO days?") is None


def test_optional_history_text_none_for_empty_history() -> None:
    assert prompts.optional_history_text({"history": [], "question": "Price?"}) is None


def test_optional_history_text_renders_prior_turns() -> None:
    text = prompts.optional_history_text(
        {
            "history": [
                {"role": "user", "content": "Do you have a Pro plan?"},
                {"role": "assistant", "content": "Yes, Pro is available."},
            ],
            "question": "How much does it cost?",
        }
    )
    assert text is not None
    assert "Do you have a Pro plan?" in text
    assert "Yes, Pro is available." in text
    assert "How much does it cost?" not in text  # question is not part of history


@pytest.mark.asyncio
async def test_conversation_consistency_prompt_includes_mid_transcript_assistant() -> None:
    llm = ScriptedJudgeLlm()
    await _judge("conversation_consistency", llm).evaluate(_chat_sample())
    assert llm.calls, "expected a rubric LLM call"
    user = llm.calls[0]["user"]
    assert "CONVERSATION:" in user
    assert "Pro is actually $99/month." in user
    assert "Pro costs $49/month." in user  # early + final assistant turns
    assert "ANSWER:" not in user
    assert "QUESTION:" not in user


@pytest.mark.asyncio
async def test_conversation_consistency_skips_without_two_assistant_turns() -> None:
    llm = ScriptedJudgeLlm()
    sample = EvaluationSample(
        input={"history": [], "question": "Hello?"},
        expected_output=None,
        actual_output="Hi!",
        context=None,
        metadata={},
    )
    result = await _judge("conversation_consistency", llm).evaluate(sample)
    assert result.label == "SKIPPED"
    assert result.explanation == _CONVERSATION_CONSISTENCY_SKIP
    assert llm.calls == []


@pytest.mark.asyncio
async def test_conversation_consistency_skips_single_assistant_in_nonempty_history() -> None:
    llm = ScriptedJudgeLlm()
    sample = EvaluationSample(
        input={
            "history": [
                {"role": "user", "content": "What is the Pro plan price?"},
                {"role": "assistant", "content": "Pro costs $49/month."},
                {"role": "user", "content": "Thanks."},
            ],
            "question": "Can you confirm once more?",
        },
        expected_output=None,
        actual_output="",
        context=None,
        metadata={},
    )
    result = await _judge("conversation_consistency", llm).evaluate(sample)
    assert result.label == "SKIPPED"
    assert result.explanation == _CONVERSATION_CONSISTENCY_SKIP
    assert llm.calls == []


_DOCS = {"documents": [{"id": "kb-1", "text": "Pro plan costs $49 per month."}]}


@pytest.mark.asyncio
async def test_resolution_skips_without_documents() -> None:
    llm = ScriptedJudgeLlm()
    sample = _chat_sample(context=None, actual_output="Pro is $49/month.")
    result = await _judge("resolution", llm).evaluate(sample)
    assert result.label == "SKIPPED"
    assert "document" in (result.explanation or "").lower()
    assert llm.calls == []


@pytest.mark.asyncio
async def test_resolution_includes_documents_and_turns_when_resolved() -> None:
    llm = ScriptedJudgeLlm({"rubric_resolution": {"reasoning": "fully answers", "level": 5}})
    sample = _chat_sample(context=_DOCS, actual_output="Pro costs $49 per month.")
    result = await _judge("resolution", llm).evaluate(sample)
    assert result.label == "resolved"
    assert result.metadata.get("resolved") is True
    assert result.metadata["turns_to_resolution"] == 3  # 2 user turns in history + question
    assert "DOCUMENTS:" in llm.calls[0]["user"]
    assert "Pro plan costs $49" in llm.calls[0]["user"]


@pytest.mark.asyncio
async def test_resolution_omits_turns_when_unresolved() -> None:
    llm = ScriptedJudgeLlm({"rubric_resolution": {"reasoning": "still unclear", "level": 2}})
    sample = _chat_sample(context=_DOCS, actual_output="Could you clarify which plan?")
    result = await _judge("resolution", llm).evaluate(sample)
    assert result.label == "unresolved"
    assert result.metadata.get("resolved") is False
    assert "turns_to_resolution" not in result.metadata
