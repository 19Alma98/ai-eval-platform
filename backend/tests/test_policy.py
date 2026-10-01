from __future__ import annotations

import uuid

import pytest

from aiobs.domain.evaluation import EvaluationResultRecord
from aiobs.regression.policy import (
    EvaluatorMetricInput,
    InvalidPolicyError,
    RegressionDeltaInput,
    evaluate_policy,
    parse_release_policy,
    percentile_nearest_rank,
    strip_meta_keys,
)


def _result(
    *,
    latency_ms: float | None = None,
    cost_usd: float | None = None,
) -> EvaluationResultRecord:
    metadata: dict[str, float] = {}
    if latency_ms is not None:
        metadata["latency_ms"] = latency_ms
    if cost_usd is not None:
        metadata["cost_usd"] = cost_usd
    return EvaluationResultRecord.create(uuid.uuid4(), uuid.uuid4(), metadata=metadata)


def _metric(
    name: str,
    *,
    mean_score: float | None,
    results: list[EvaluationResultRecord] | None = None,
) -> EvaluatorMetricInput:
    return EvaluatorMetricInput(
        evaluator_id=uuid.uuid4(),
        evaluator_name=name,
        mean_score=mean_score,
        results=tuple(results or ()),
    )


def test_strip_meta_keys() -> None:
    raw = {
        "project_id": "p",
        "quality": {"min": 0.8},
        "api_base_url": "http://localhost",
    }
    assert strip_meta_keys(raw) == {"quality": {"min": 0.8}}


def test_parse_full_policy() -> None:
    policy = parse_release_policy(
        {
            "quality": {"min": 0.85},
            "groundedness": {"min": 0.9},
            "latency": {"p95_max_ms": 2000},
            "cost": {"max_per_request_usd": 0.03},
            "regression": {"max_delta": -0.03},
        }
    )
    assert len(policy.absolute_mins) == 2
    assert policy.latency is not None and policy.latency.p95_max_ms == 2000
    assert policy.cost is not None and policy.cost.max_per_request_usd == 0.03
    assert policy.regression is not None and policy.regression.max_delta == -0.03


def test_parse_rejects_unknown_keys_and_empty() -> None:
    with pytest.raises(InvalidPolicyError, match="unsupported"):
        parse_release_policy({"quality": {"min": 0.8, "max": 1.0}})
    with pytest.raises(InvalidPolicyError, match="at least one"):
        parse_release_policy({"project_id": "x"})
    with pytest.raises(InvalidPolicyError, match="number"):
        parse_release_policy({"quality": {"min": "high"}})


def test_percentile_nearest_rank() -> None:
    values = [100.0, 200.0, 300.0, 400.0, 500.0, 600.0, 700.0, 800.0, 900.0, 1000.0]
    assert percentile_nearest_rank(values, 95.0) == 1000.0
    assert percentile_nearest_rank([10.0, 20.0], 95.0) == 20.0


def test_evaluate_absolute_min_pass_fail_unavailable() -> None:
    policy = parse_release_policy({"quality": {"min": 0.85}})
    passed = evaluate_policy(policy, candidate=[_metric("quality", mean_score=0.91)])
    assert passed.status == "passed"
    assert passed.checks[0].status == "passed"

    failed = evaluate_policy(policy, candidate=[_metric("quality", mean_score=0.5)])
    assert failed.status == "failed"
    assert failed.checks[0].status == "failed"

    missing = evaluate_policy(policy, candidate=[])
    assert missing.status == "failed"
    assert missing.checks[0].status == "unavailable"


def test_evaluate_latency_p95_and_cost_mean() -> None:
    policy = parse_release_policy(
        {
            "latency": {"p95_max_ms": 2000},
            "cost": {"max_per_request_usd": 0.03},
        }
    )
    results = [
        _result(latency_ms=1000, cost_usd=0.01),
        _result(latency_ms=1500, cost_usd=0.02),
        _result(latency_ms=2500, cost_usd=0.04),
    ]
    # For n=3, ceil(0.95*3)=3 → 2500 > 2000 fail; mean cost = 0.02333… pass
    eval_result = evaluate_policy(
        policy,
        candidate=[
            _metric("latency", mean_score=0.0, results=results),
            _metric("cost", mean_score=1.0, results=results),
        ],
    )
    by_metric = {c.metric: c for c in eval_result.checks}
    assert by_metric["latency.p95"].status == "failed"
    assert by_metric["latency.p95"].actual == 2500.0
    assert by_metric["cost.max_per_request_usd"].status == "passed"
    assert by_metric["cost.max_per_request_usd"].actual is not None
    assert abs(by_metric["cost.max_per_request_usd"].actual - 0.07 / 3) < 1e-12


def test_evaluate_regression_max_delta() -> None:
    policy = parse_release_policy({"regression": {"max_delta": -0.03}})
    ok = evaluate_policy(
        policy,
        candidate=[],
        regression_deltas=[RegressionDeltaInput(evaluator_name="quality", mean_score_delta=-0.02)],
    )
    assert ok.status == "passed"

    bad = evaluate_policy(
        policy,
        candidate=[],
        regression_deltas=[RegressionDeltaInput(evaluator_name="quality", mean_score_delta=-0.05)],
    )
    assert bad.status == "failed"
    assert bad.checks[0].metric == "regression.quality.mean_score"

    empty = evaluate_policy(policy, candidate=[], regression_deltas=[])
    assert empty.status == "failed"
    assert empty.checks[0].status == "unavailable"
