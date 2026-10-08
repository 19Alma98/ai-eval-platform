from __future__ import annotations

import pytest

from aiobs.evaluation.deterministic import MRREvaluator
from aiobs.evaluation.protocol import EvaluationSample


@pytest.mark.asyncio
async def test_mrr_first_rank() -> None:
    ev = MRREvaluator({"k": 5})
    sample = EvaluationSample(
        input="q",
        expected_output="a",
        actual_output=None,
        context={"retrieved_doc_ids": ["a", "b", "c"]},
        metadata={"expected_doc_ids": ["a"]},
    )
    result = await ev.evaluate(sample)
    assert result.score == 1.0
    assert result.label is None
    assert result.metadata["rank"] == 1


@pytest.mark.asyncio
async def test_mrr_second_rank() -> None:
    ev = MRREvaluator({"k": 5})
    sample = EvaluationSample(
        input="q",
        expected_output="a",
        actual_output=None,
        context={"documents": [{"id": "x"}, {"id": "a"}, {"id": "y"}]},
        metadata={"expected_doc_ids": ["a", "b"]},
    )
    result = await ev.evaluate(sample)
    assert result.score == 0.5
    assert result.metadata["rank"] == 2


@pytest.mark.asyncio
async def test_mrr_miss_outside_k() -> None:
    ev = MRREvaluator({"k": 2})
    sample = EvaluationSample(
        input="q",
        expected_output="a",
        actual_output=None,
        context={"retrieved_doc_ids": ["x", "y", "a"]},
        metadata={"expected_doc_ids": ["a"]},
    )
    result = await ev.evaluate(sample)
    assert result.score == 0.0
    assert result.metadata["rank"] is None


@pytest.mark.asyncio
async def test_mrr_skipped_empty_expected() -> None:
    ev = MRREvaluator({"k": 5})
    sample = EvaluationSample(
        input="q",
        expected_output="a",
        actual_output=None,
        context={"retrieved_doc_ids": ["a"]},
        metadata={"expected_doc_ids": []},
    )
    result = await ev.evaluate(sample)
    assert result.label == "SKIPPED"


@pytest.mark.asyncio
async def test_mrr_fail_missing_retrieved() -> None:
    ev = MRREvaluator({"k": 5})
    sample = EvaluationSample(
        input="q",
        expected_output="a",
        actual_output=None,
        context={},
        metadata={"expected_doc_ids": ["a"]},
    )
    result = await ev.evaluate(sample)
    assert result.score == 0.0
    assert result.label == "FAIL"


def test_mrr_k_must_be_at_least_one() -> None:
    with pytest.raises(ValueError, match="k"):
        MRREvaluator({"k": 0})
