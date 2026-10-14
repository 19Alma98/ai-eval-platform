from __future__ import annotations

from typing import Any

import pytest

from opengrade_server.regression.policy import (
    ExperimentMetricRule,
    InvalidPolicyError,
    evaluate_policy,
    parse_release_policy,
)


def test_parse_experiment_metric_rules() -> None:
    policy = parse_release_policy(
        {"experiment_metrics": {"cost_usd": {"max": 2}, "acc": {"min": 0.5, "max": 1}}}
    )
    assert policy.experiment_metrics == (
        ExperimentMetricRule("cost_usd", None, 2.0),
        ExperimentMetricRule("acc", 0.5, 1.0),
    )
    assert policy.absolute_mins == ()


@pytest.mark.parametrize(
    ("raw", "match"),
    [
        ({"experiment_metrics": {}}, "at least one metric"),
        ({"experiment_metrics": {"c": 1}}, "must be an object"),
        ({"experiment_metrics": {"c": {}}}, "requires min or max"),
        ({"experiment_metrics": {"c": {"avg": 1}}}, "unsupported keys"),
        ({"experiment_metrics": {"c": {"max": "2"}}}, "must be a number"),
        ({"experiment_metrics": {"c": {"min": 3, "max": 2}}}, "min must be <= max"),
        ({"experiment_metrics": {"bad key!": {"max": 2}}}, "invalid metric key"),
    ],
)
def test_parse_rejects_bad_rules(raw: dict[str, Any], match: str) -> None:
    with pytest.raises(InvalidPolicyError, match=match):
        parse_release_policy(raw)


def test_evaluate_bounds_and_missing_metric() -> None:
    policy = parse_release_policy(
        {"experiment_metrics": {"lat": {"min": 10, "max": 20}, "gone": {"max": 1}}}
    )
    result = evaluate_policy(policy, candidate=[], experiment_metrics={"lat": 15.0})
    assert [(c.metric, c.actual, c.threshold, c.status) for c in result.checks] == [
        ("experiment_metrics.lat.min", 15.0, 10.0, "passed"),
        ("experiment_metrics.lat.max", 15.0, 20.0, "passed"),
        ("experiment_metrics.gone.max", None, 1.0, "unavailable"),
    ]
    assert result.status == "failed"

    over = evaluate_policy(
        parse_release_policy({"experiment_metrics": {"lat": {"max": 20}}}),
        candidate=[],
        experiment_metrics={"lat": 25.0},
    )
    assert [c.status for c in over.checks] == ["failed"]
    assert over.status == "failed"
