from __future__ import annotations

import pytest

from aiobs.evaluation.deterministic import HitAtKEvaluator
from aiobs.evaluation.protocol import EvaluationSample


@pytest.mark.asyncio
async def test_hit_at_k_pass() -> None:
    ev = HitAtKEvaluator({"k": 2})
    sample = EvaluationSample(
        input="q",
        expected_output="a",
        actual_output="ans",
        context={"documents": [{"id": "b"}, {"id": "a"}, {"id": "c"}]},
        metadata={"expected_doc_ids": ["a"]},
    )
    result = await ev.evaluate(sample)
    assert result.score == 1.0
    assert result.label == "PASS"


@pytest.mark.asyncio
async def test_hit_at_k_miss() -> None:
    ev = HitAtKEvaluator({"k": 2})
    sample = EvaluationSample(
        input="q",
        expected_output="a",
        actual_output="ans",
        context={"documents": [{"id": "b"}, {"id": "d"}, {"id": "c"}]},
        metadata={"expected_doc_ids": ["a"]},
    )
    result = await ev.evaluate(sample)
    assert result.score == 0.0
    assert result.label == "FAIL"


@pytest.mark.asyncio
async def test_hit_at_k_truncates_at_k() -> None:
    ev = HitAtKEvaluator({"k": 2})
    sample = EvaluationSample(
        input="q",
        expected_output="a",
        actual_output="ans",
        context={"documents": [{"id": "b"}, {"id": "d"}, {"id": "a"}]},
        metadata={"expected_doc_ids": ["a"]},
    )
    result = await ev.evaluate(sample)
    assert result.score == 0.0
    assert result.label == "FAIL"


@pytest.mark.asyncio
async def test_hit_at_k_retrieved_doc_ids() -> None:
    ev = HitAtKEvaluator({"k": 3})
    sample = EvaluationSample(
        input="q",
        expected_output="a",
        actual_output="ans",
        context={"retrieved_doc_ids": ["x", "y", "target"]},
        metadata={"expected_doc_ids": ["target"]},
    )
    result = await ev.evaluate(sample)
    assert result.score == 1.0
    assert result.label == "PASS"


@pytest.mark.asyncio
async def test_hit_at_k_skipped_missing_expected() -> None:
    ev = HitAtKEvaluator({"k": 5})
    sample = EvaluationSample(
        input="q",
        expected_output="a",
        actual_output="ans",
        context={"retrieved_doc_ids": ["a"]},
        metadata={},
    )
    result = await ev.evaluate(sample)
    assert result.score is None
    assert result.label == "SKIPPED"


@pytest.mark.asyncio
async def test_hit_at_k_skipped_missing_retrieved() -> None:
    ev = HitAtKEvaluator({"k": 5})
    sample = EvaluationSample(
        input="q",
        expected_output="a",
        actual_output="ans",
        context={},
        metadata={"expected_doc_ids": ["a"]},
    )
    result = await ev.evaluate(sample)
    assert result.score is None
    assert result.label == "SKIPPED"


@pytest.mark.asyncio
async def test_hit_at_k_default_k() -> None:
    ev = HitAtKEvaluator({"kind": "hit_at_k"})
    docs = [{"id": f"doc-{i}"} for i in range(10)]
    sample = EvaluationSample(
        input="q",
        expected_output="a",
        actual_output="ans",
        context={"documents": docs},
        metadata={"expected_doc_ids": ["doc-4"]},
    )
    result = await ev.evaluate(sample)
    assert result.score == 1.0
    assert result.label == "PASS"


def test_hit_at_k_k_must_be_at_least_one() -> None:
    with pytest.raises(ValueError, match="k"):
        HitAtKEvaluator({"k": 0})
