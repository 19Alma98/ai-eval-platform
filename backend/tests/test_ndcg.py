from __future__ import annotations

import math

import pytest

from opengrade_server.evaluation.deterministic import NdcgEvaluator, _binary_dcg
from opengrade_server.evaluation.protocol import EvaluationSample


@pytest.mark.asyncio
async def test_ndcg_perfect() -> None:
    ev = NdcgEvaluator({"k": 3})
    sample = EvaluationSample(
        input="q",
        expected_output="a",
        actual_output=None,
        context={"documents": [{"id": "a"}, {"id": "b"}, {"id": "c"}]},
        metadata={"expected_doc_ids": ["a", "b"]},
    )
    result = await ev.evaluate(sample)
    assert result.score == pytest.approx(1.0)
    assert result.label is None
    assert result.metadata["hits"] == 2


@pytest.mark.asyncio
async def test_ndcg_partial_ranking() -> None:
    ev = NdcgEvaluator({"k": 3})
    sample = EvaluationSample(
        input="q",
        expected_output="a",
        actual_output=None,
        context={"documents": [{"id": "x"}, {"id": "a"}, {"id": "y"}]},
        metadata={"expected_doc_ids": ["a", "b"]},
    )
    result = await ev.evaluate(sample)
    # One relevant at rank 2; ideal has two relevants at ranks 1–2.
    dcg = (math.pow(2, 1) - 1) / math.log2(3)
    idcg = (math.pow(2, 1) - 1) / math.log2(2) + (math.pow(2, 1) - 1) / math.log2(3)
    assert result.score == pytest.approx(dcg / idcg)
    assert result.metadata["hits"] == 1


@pytest.mark.asyncio
async def test_ndcg_miss() -> None:
    ev = NdcgEvaluator({"k": 2})
    sample = EvaluationSample(
        input="q",
        expected_output="a",
        actual_output=None,
        context={"documents": [{"id": "x"}, {"id": "y"}, {"id": "a"}]},
        metadata={"expected_doc_ids": ["a", "b"]},
    )
    result = await ev.evaluate(sample)
    assert result.score == 0.0
    assert result.metadata["hits"] == 0


@pytest.mark.asyncio
async def test_ndcg_skipped_missing_expected() -> None:
    ev = NdcgEvaluator({"k": 5})
    sample = EvaluationSample(
        input="q",
        expected_output="a",
        actual_output=None,
        context={"documents": [{"id": "a"}]},
        metadata={},
    )
    result = await ev.evaluate(sample)
    assert result.score is None
    assert result.label == "SKIPPED"


@pytest.mark.asyncio
async def test_ndcg_fail_empty_retrieved() -> None:
    ev = NdcgEvaluator({"k": 5})
    sample = EvaluationSample(
        input="q",
        expected_output="a",
        actual_output=None,
        context={"documents": []},
        metadata={"expected_doc_ids": ["a"]},
    )
    result = await ev.evaluate(sample)
    assert result.score == 0.0
    assert result.label == "FAIL"


def test_ndcg_k_must_be_at_least_one() -> None:
    with pytest.raises(ValueError, match="k"):
        NdcgEvaluator({"k": 0})


def test_binary_dcg_empty() -> None:
    assert _binary_dcg([]) == 0.0
