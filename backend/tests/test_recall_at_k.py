from __future__ import annotations

import pytest

from aiobs.evaluation.deterministic import RecallAtKEvaluator
from aiobs.evaluation.protocol import EvaluationSample


@pytest.mark.asyncio
async def test_recall_at_k_full() -> None:
    ev = RecallAtKEvaluator({"k": 3})
    sample = EvaluationSample(
        input="q",
        expected_output="a",
        actual_output=None,
        context={"retrieved_doc_ids": ["a", "b", "c"]},
        metadata={"expected_doc_ids": ["a", "b"]},
    )
    result = await ev.evaluate(sample)
    assert result.score == 1.0
    assert result.label is None
    assert result.metadata["hits"] == 2


@pytest.mark.asyncio
async def test_recall_at_k_partial() -> None:
    ev = RecallAtKEvaluator({"k": 2})
    sample = EvaluationSample(
        input="q",
        expected_output="a",
        actual_output=None,
        context={"documents": [{"id": "a"}, {"id": "x"}, {"id": "b"}]},
        metadata={"expected_doc_ids": ["a", "b"]},
    )
    result = await ev.evaluate(sample)
    assert result.score == 0.5
    assert result.metadata["hits"] == 1
    assert result.metadata["n_expected"] == 2


@pytest.mark.asyncio
async def test_recall_at_k_miss() -> None:
    ev = RecallAtKEvaluator({"k": 2})
    sample = EvaluationSample(
        input="q",
        expected_output="a",
        actual_output=None,
        context={"retrieved_doc_ids": ["x", "y", "a"]},
        metadata={"expected_doc_ids": ["a", "b"]},
    )
    result = await ev.evaluate(sample)
    assert result.score == 0.0


@pytest.mark.asyncio
async def test_recall_at_k_skipped_missing_expected() -> None:
    ev = RecallAtKEvaluator({"k": 5})
    sample = EvaluationSample(
        input="q",
        expected_output="a",
        actual_output=None,
        context={"retrieved_doc_ids": ["a"]},
        metadata={},
    )
    result = await ev.evaluate(sample)
    assert result.score is None
    assert result.label == "SKIPPED"


@pytest.mark.asyncio
async def test_recall_at_k_fail_empty_retrieved() -> None:
    ev = RecallAtKEvaluator({"k": 5})
    sample = EvaluationSample(
        input="q",
        expected_output="a",
        actual_output=None,
        context={"retrieved_doc_ids": []},
        metadata={"expected_doc_ids": ["a"]},
    )
    result = await ev.evaluate(sample)
    assert result.score == 0.0
    assert result.label == "FAIL"


def test_recall_at_k_k_must_be_at_least_one() -> None:
    with pytest.raises(ValueError, match="k"):
        RecallAtKEvaluator({"k": 0})
