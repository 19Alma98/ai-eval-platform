from __future__ import annotations

import uuid

import pytest

from aiobs.domain.dataset import DatasetItem
from aiobs.domain.evaluation import EvaluationResultRecord, EvaluationRun
from aiobs.domain.evaluator import Evaluator
from aiobs.evaluation.judges.warnings import JUDGE_MODEL_UNSUITABLE, unsuitable_model_warning
from aiobs.evaluation.runner import EvaluationRunner
from support.fake_llm import ScriptedJudgeLlm


def _rec(label: str, **metadata: object) -> EvaluationResultRecord:
    return EvaluationResultRecord.create(
        uuid.uuid4(),
        uuid.uuid4(),
        score=None,
        label=label,
        explanation=None,
        metadata=dict(metadata),
        duration_ms=0,
    )


def _invalid() -> EvaluationResultRecord:
    return _rec("ERROR", error_type="judge_output_invalid", model="tiny", method="claims")


@pytest.mark.parametrize(
    ("n_invalid", "expected"),
    [(19, False), (20, False), (21, True)],
)
def test_threshold_is_strictly_above_twenty_percent(n_invalid: int, expected: bool) -> None:
    results = [_invalid() for _ in range(n_invalid)]
    results += [_rec("PASS") for _ in range(100 - n_invalid)]
    detail = unsuitable_model_warning(results)
    assert (detail is not None) is expected
    if detail is not None:
        assert detail["model"] == "tiny"
        assert detail["method"] == "claims"
        assert detail["failure_rate"] == pytest.approx(0.21)
        assert "rubric" in detail["message"]


def test_skipped_missing_output_and_provider_errors_are_excluded() -> None:
    results = [_invalid(), _invalid()]
    results += [_rec("SKIPPED") for _ in range(20)]
    results += [_rec("FAIL", missing_output=True) for _ in range(20)]
    results += [_rec("ERROR", error_type="llm_unavailable") for _ in range(6)]
    # 2 invalid out of 8 evaluated (2 invalid + 6 provider errors) = 25%
    assert unsuitable_model_warning(results) is not None
    assert unsuitable_model_warning([_rec("SKIPPED")]) is None


@pytest.mark.asyncio
async def test_runner_records_prompt_version_and_warning() -> None:
    from aiobs.evaluation.judges.evaluators import JudgeDefaults, create_llm_judge

    llm = ScriptedJudgeLlm({"rubric_answer_relevance": ["bad", "bad"]})
    entity = Evaluator.create(
        uuid.uuid4(), "answer_relevance", "llm_judge", {"kind": "answer_relevance"}
    )
    runner = EvaluationRunner(
        resolve_evaluator=lambda e: create_llm_judge(
            "answer_relevance", e.config, llm, defaults=JudgeDefaults(model="tiny")
        )
    )
    item = DatasetItem.create(uuid.uuid4(), input="q", actual_output="a")
    run = EvaluationRun.create(uuid.uuid4(), entity.id, status="PENDING")
    run, results = await runner.run_evaluator(run=run, evaluator_entity=entity, items=[item])

    assert run.metadata["prompt_version"] == "answer_relevance.rubric.v3"
    assert run.metadata["warnings"] == [JUDGE_MODEL_UNSUITABLE]
    assert run.metadata["warning_detail"]["model"] == "tiny"
    assert results[0].metadata["error_type"] == "judge_output_invalid"


@pytest.mark.asyncio
async def test_runner_without_prompt_version_or_warning() -> None:
    entity = Evaluator.create(uuid.uuid4(), "exact", "deterministic", {"kind": "exact_match"})
    from aiobs.evaluation.deterministic import ExactMatchEvaluator

    runner = EvaluationRunner(resolve_evaluator=lambda e: ExactMatchEvaluator({}))
    item = DatasetItem.create(uuid.uuid4(), input="q", expected_output="a", actual_output="a")
    run = EvaluationRun.create(uuid.uuid4(), entity.id, status="PENDING")
    run, _ = await runner.run_evaluator(run=run, evaluator_entity=entity, items=[item])
    assert "prompt_version" not in run.metadata
    assert "warnings" not in run.metadata
