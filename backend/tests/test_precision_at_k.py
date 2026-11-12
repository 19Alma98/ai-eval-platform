from __future__ import annotations

import pytest

from opengrade_server.evaluation.deterministic import PrecisionAtKEvaluator
from opengrade_server.evaluation.protocol import EvaluationSample


@pytest.mark.asyncio
async def test_precision_at_k_full_slot() -> None:
    ev = PrecisionAtKEvaluator({"k": 2})
    sample = EvaluationSample(
        input="q",
        expected_output="a",
        actual_output=None,
        context={"documents": [{"id": "a"}, {"id": "b"}, {"id": "c"}]},
        metadata={"expected_doc_ids": ["a", "b"]},
    )
    result = await ev.evaluate(sample)
    assert result.score == 1.0
    assert result.label is None
    assert result.metadata["hits"] == 2


@pytest.mark.asyncio
async def test_precision_at_k_partial() -> None:
    ev = PrecisionAtKEvaluator({"k": 2})
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
async def test_precision_at_k_miss() -> None:
    ev = PrecisionAtKEvaluator({"k": 2})
    sample = EvaluationSample(
        input="q",
        expected_output="a",
        actual_output=None,
        context={"documents": [{"id": "x"}, {"id": "y"}, {"id": "a"}]},
        metadata={"expected_doc_ids": ["a", "b"]},
    )
    result = await ev.evaluate(sample)
    assert result.score == 0.0


@pytest.mark.asyncio
async def test_precision_at_k_denominator_is_k() -> None:
    """Even with fewer expected docs than k, denominator stays k."""
    ev = PrecisionAtKEvaluator({"k": 5})
    sample = EvaluationSample(
        input="q",
        expected_output="a",
        actual_output=None,
        context={"documents": [{"id": "a"}, {"id": "x"}, {"id": "y"}, {"id": "z"}, {"id": "w"}]},
        metadata={"expected_doc_ids": ["a"]},
    )
    result = await ev.evaluate(sample)
    assert result.score == pytest.approx(1 / 5)


@pytest.mark.asyncio
async def test_precision_at_k_skipped_missing_expected() -> None:
    ev = PrecisionAtKEvaluator({"k": 5})
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
async def test_precision_at_k_fail_empty_retrieved() -> None:
    ev = PrecisionAtKEvaluator({"k": 5})
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


def test_precision_at_k_k_must_be_at_least_one() -> None:
    with pytest.raises(ValueError, match="k"):
        PrecisionAtKEvaluator({"k": 0})
