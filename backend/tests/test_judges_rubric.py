from __future__ import annotations

import pytest

from aiobs_server.evaluation.judges import prompts
from aiobs_server.evaluation.judges.parsing import CallOptions
from aiobs_server.evaluation.judges.rubric import level_to_score, rubric_judge
from support.fake_llm import ScriptedJudgeLlm


@pytest.mark.parametrize(("level", "score"), [(1, 0.0), (2, 0.25), (3, 0.5), (4, 0.75), (5, 1.0)])
def test_level_to_score(level: int, score: float) -> None:
    assert level_to_score(level) == score


@pytest.mark.asyncio
async def test_rubric_judge_parses_level() -> None:
    llm = ScriptedJudgeLlm({"rubric_answer_relevance": {"reasoning": "partial", "level": 3}})
    out, calls = await rubric_judge(
        llm,
        system=prompts.RUBRICS["answer_relevance"],
        user="u",
        options=CallOptions(model=None, temperature=None),
    )
    assert out.level == 3
    assert out.reasoning == "partial"
    assert calls == 1
