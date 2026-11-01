"""Relative bounds vs the baseline: latency / cost ``max_increase_pct`` and run-metric
``max_increase`` / ``max_decrease`` (+ ``_pct``)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from opengrade_server.domain.evaluation import EvaluationResultRecord
from opengrade_server.regression.policy import (
    EvaluatorMetricInput,
    InvalidPolicyError,
    evaluate_policy,
    parse_release_policy,
    percent_change,
    strip_baseline_rules,
)


def _metric(name: str, key: str, values: list[float]) -> EvaluatorMetricInput:
    run_id = uuid.uuid4()
    return EvaluatorMetricInput(
        evaluator_id=uuid.uuid4(),
        evaluator_name=name,
        mean_score=1.0,
        results=tuple(
            EvaluationResultRecord.create(run_id, uuid.uuid4(), score=1.0, metadata={key: v})
            for v in values
        ),
    )


def _rows(result: Any) -> list[tuple[str, float | None, float | None, str]]:
    return [
        (c.metric, None if c.actual is None else round(c.actual, 6), c.threshold, c.status)
        for c in result.checks
    ]


def test_parse_relative_rules_and_needs_baseline() -> None:
    policy = parse_release_policy(
        {
            "latency": {"max_increase_pct": 20},
            "cost": {"max_per_request_usd": 0.01, "max_increase_pct": 10},
            "experiment_metrics": {"opengrade.error_rate": {"max_increase": 0.01}},
        }
    )
    assert policy.latency is not None and policy.latency.p95_max_ms is None
    assert policy.latency.max_increase_pct == 20.0
    assert policy.cost is not None and policy.cost.max_increase_pct == 10.0
    assert policy.experiment_metrics[0].is_relative
    assert policy.needs_baseline()
    assert not parse_release_policy({"latency": {"p95_max_ms": 100}}).needs_baseline()


@pytest.mark.parametrize(
    ("raw", "match"),
    [
        ({"latency": {}}, "requires p95_max_ms or max_increase_pct"),
        ({"cost": {}}, "requires max_per_request_usd or max_increase_pct"),
        ({"latency": {"max_increase_pct": -5}}, "must be >= 0"),
        ({"experiment_metrics": {"m": {"max_decrease": -1}}}, "must be >= 0"),
        ({"latency": {"max_increase_pct": "20"}}, "must be a number"),
    ],
)
def test_parse_rejects_bad_relative_rules(raw: dict[str, Any], match: str) -> None:
    with pytest.raises(InvalidPolicyError, match=match):
        parse_release_policy(raw)


def test_latency_increase_pct_vs_baseline() -> None:
    policy = parse_release_policy({"latency": {"p95_max_ms": 1000, "max_increase_pct": 20}})
    base = [_metric("latency", "latency_ms", [100.0] * 10)]
    slower = [_metric("latency", "latency_ms", [130.0] * 10)]
    result = evaluate_policy(policy, candidate=slower, baseline=base)
    assert _rows(result) == [
        ("latency.p95", 130.0, 1000.0, "passed"),
        ("latency.p95.max_increase_pct", 30.0, 20.0, "failed"),
    ]
    assert result.status == "failed"

    ok = evaluate_policy(
        policy, candidate=[_metric("latency", "latency_ms", [110.0] * 10)], baseline=base
    )
    assert ok.status == "passed"


def test_cost_increase_pct_and_missing_baseline_data() -> None:
    policy = parse_release_policy({"cost": {"max_increase_pct": 10}})
    cand = [_metric("cost", "cost_usd", [0.002, 0.002])]
    passed = evaluate_policy(
        policy, candidate=cand, baseline=[_metric("cost", "cost_usd", [0.002])]
    )
    assert _rows(passed) == [("cost.mean_per_request_usd.max_increase_pct", 0.0, 10.0, "passed")]
    missing = evaluate_policy(policy, candidate=cand, baseline=[])
    assert _rows(missing) == [
        ("cost.mean_per_request_usd.max_increase_pct", None, 10.0, "unavailable")
    ]
    assert missing.status == "failed"


def test_increase_from_zero_baseline_fails() -> None:
    policy = parse_release_policy({"cost": {"max_increase_pct": 10}})
    result = evaluate_policy(
        policy,
        candidate=[_metric("cost", "cost_usd", [0.01])],
        baseline=[_metric("cost", "cost_usd", [0.0])],
    )
    assert _rows(result) == [("cost.mean_per_request_usd.max_increase_pct", None, 10.0, "failed")]
    assert percent_change(0.0, 0.0) == 0.0
    assert percent_change(1.0, 0.0) is None


def test_experiment_metric_relative_bounds() -> None:
    policy = parse_release_policy(
        {
            "experiment_metrics": {
                "opengrade.error_rate": {"max": 0.1, "max_increase": 0.01},
                "accuracy": {"max_decrease": 0.02, "max_decrease_pct": 5},
                "opengrade.latency_p95_ms": {"max_increase_pct": 25},
            }
        }
    )
    result = evaluate_policy(
        policy,
        candidate=[],
        experiment_metrics={
            "opengrade.error_rate": 0.05,
            "accuracy": 0.90,
            "opengrade.latency_p95_ms": 120.0,
        },
        baseline_experiment_metrics={
            "opengrade.error_rate": 0.0,
            "accuracy": 0.91,
            "opengrade.latency_p95_ms": 100.0,
        },
    )
    assert _rows(result) == [
        ("experiment_metrics.opengrade.error_rate.max", 0.05, 0.1, "passed"),
        ("experiment_metrics.opengrade.error_rate.max_increase", 0.05, 0.01, "failed"),
        ("experiment_metrics.accuracy.max_decrease", 0.01, 0.02, "passed"),
        ("experiment_metrics.accuracy.max_decrease_pct", 1.098901, 5.0, "passed"),
        ("experiment_metrics.opengrade.latency_p95_ms.max_increase_pct", 20.0, 25.0, "passed"),
    ]


def test_experiment_metric_improvement_passes_and_zero_baseline_direction() -> None:
    policy = parse_release_policy(
        {"experiment_metrics": {"err": {"max_increase_pct": 10}, "acc": {"max_decrease_pct": 1}}}
    )
    result = evaluate_policy(
        policy,
        candidate=[],
        experiment_metrics={"err": 0.0, "acc": 0.5},
        baseline_experiment_metrics={"err": 0.2, "acc": 0.0},
    )
    # err dropped (better); acc rose from 0 (unbounded %, but in the good direction)
    assert _rows(result) == [
        ("experiment_metrics.err.max_increase_pct", -100.0, 10.0, "passed"),
        ("experiment_metrics.acc.max_decrease_pct", None, 1.0, "passed"),
    ]


def test_strip_baseline_rules() -> None:
    raw = {
        "groundedness": {"min": 0.7},
        "regression": {"max_delta": -0.05},
        "latency": {"p95_max_ms": 2000, "max_increase_pct": 20},
        "cost": {"max_increase_pct": 10},
        "experiment_metrics": {
            "opengrade.error_rate": {"max": 0.1, "max_increase": 0.01},
            "opengrade.latency_p95_ms": {"max_increase_pct": 25},
        },
        "groups": {"by": "category", "max_delta": -0.1},
    }
    assert strip_baseline_rules(raw) == {
        "groundedness": {"min": 0.7},
        "latency": {"p95_max_ms": 2000},
        "experiment_metrics": {"opengrade.error_rate": {"max": 0.1}},
        "groups": {"by": "category"},
    }
    stripped = parse_release_policy(strip_baseline_rules(raw))
    assert not stripped.needs_baseline()
    # groups with nothing left to re-apply is dropped rather than made invalid
    assert strip_baseline_rules(
        {"latency": {"p95_max_ms": 1}, "groups": {"by": "c", "max_delta": -0.1}}
    ) == {"latency": {"p95_max_ms": 1}}
