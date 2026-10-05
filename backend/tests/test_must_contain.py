from __future__ import annotations

import pytest

from aiobs.evaluation.deterministic import MustContainEvaluator
from aiobs.evaluation.protocol import EvaluationSample


@pytest.mark.asyncio
async def test_must_contain_pass() -> None:
    ev = MustContainEvaluator({})
    sample = EvaluationSample(
        input="q",
        expected_output="Full-time employees receive 20 days of PTO.",
        actual_output="You get 20 days of PTO each year.",
        context=None,
        metadata={"must_contain": ["20 days"]},
    )
    result = await ev.evaluate(sample)
    assert result.score == 1.0
    assert result.label == "PASS"
    assert result.metadata["missing"] == []


@pytest.mark.asyncio
async def test_must_contain_fail_reports_missing() -> None:
    ev = MustContainEvaluator({})
    sample = EvaluationSample(
        input="q",
        expected_output="Use GlobalProtect VPN.",
        actual_output="Connect with any VPN client.",
        context=None,
        metadata={"must_contain": ["GlobalProtect", "VPN"]},
    )
    result = await ev.evaluate(sample)
    assert result.score == 0.0
    assert result.label == "FAIL"
    assert result.metadata["missing"] == ["GlobalProtect"]


@pytest.mark.asyncio
async def test_must_contain_case_insensitive_by_default() -> None:
    ev = MustContainEvaluator({})
    sample = EvaluationSample(
        input="q",
        expected_output="a",
        actual_output="use globalprotect vpn",
        context=None,
        metadata={"must_contain": ["GlobalProtect"]},
    )
    result = await ev.evaluate(sample)
    assert result.score == 1.0


@pytest.mark.asyncio
async def test_must_contain_skipped_when_absent() -> None:
    ev = MustContainEvaluator({})
    sample = EvaluationSample(
        input="q",
        expected_output="a",
        actual_output="anything",
        context=None,
        metadata={"expected_doc_ids": ["pto"]},
    )
    result = await ev.evaluate(sample)
    assert result.score is None
    assert result.label == "SKIPPED"


@pytest.mark.asyncio
async def test_must_contain_skipped_missing_actual() -> None:
    ev = MustContainEvaluator({})
    sample = EvaluationSample(
        input="q",
        expected_output="a",
        actual_output=None,
        context=None,
        metadata={"must_contain": ["x"]},
    )
    result = await ev.evaluate(sample)
    assert result.score is None
    assert result.label == "SKIPPED"
