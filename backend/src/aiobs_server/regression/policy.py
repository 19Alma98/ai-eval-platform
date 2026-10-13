from __future__ import annotations

import math
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from aiobs_server.domain.evaluation import EvaluationResultRecord
from aiobs_server.domain.experiment_metric import METRIC_KEY_PATTERN

CheckStatus = Literal["passed", "failed", "unavailable"]
OverallStatus = Literal["passed", "failed"]

META_KEYS = frozenset(
    {
        "api_base_url",
        "base_url",
        "project_id",
        "experiment_id",
        "baseline_experiment_id",
    }
)

_LATENCY_KEYS = frozenset({"p95_max_ms"})
_COST_KEYS = frozenset({"max_per_request_usd"})
_MIN_KEYS = frozenset({"min"})
_REGRESSION_KEYS = frozenset({"max_delta", "allow_insufficient_n"})
_EXPERIMENT_METRIC_KEYS = frozenset({"min", "max"})
EXPERIMENT_METRICS_KEY = "experiment_metrics"


class InvalidPolicyError(ValueError):
    """Policy dict is malformed or uses unsupported keys."""


@dataclass(frozen=True, slots=True)
class AbsoluteMinRule:
    evaluator_name: str
    min_score: float


@dataclass(frozen=True, slots=True)
class LatencyP95Rule:
    evaluator_name: str
    p95_max_ms: float


@dataclass(frozen=True, slots=True)
class CostMeanRule:
    evaluator_name: str
    max_per_request_usd: float


@dataclass(frozen=True, slots=True)
class RegressionRule:
    max_delta: float
    allow_insufficient_n: bool = False


@dataclass(frozen=True, slots=True)
class ExperimentMetricRule:
    key: str
    min_value: float | None = None
    max_value: float | None = None


@dataclass(frozen=True, slots=True)
class ReleasePolicy:
    absolute_mins: tuple[AbsoluteMinRule, ...]
    latency: LatencyP95Rule | None
    cost: CostMeanRule | None
    regression: RegressionRule | None
    experiment_metrics: tuple[ExperimentMetricRule, ...] = ()


@dataclass(frozen=True, slots=True)
class PolicyCheck:
    metric: str
    actual: float | None
    threshold: float | None
    status: CheckStatus


@dataclass(frozen=True, slots=True)
class PolicyEvaluation:
    status: OverallStatus
    checks: tuple[PolicyCheck, ...]


@dataclass(frozen=True, slots=True)
class EvaluatorMetricInput:
    evaluator_id: uuid.UUID
    evaluator_name: str
    mean_score: float | None
    results: tuple[EvaluationResultRecord, ...]


@dataclass(frozen=True, slots=True)
class RegressionDeltaInput:
    evaluator_name: str
    mean_score_delta: float | None
    insufficient_n: bool = False


def strip_meta_keys(raw: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in raw.items() if k not in META_KEYS}


def parse_release_policy(raw: dict[str, Any]) -> ReleasePolicy:
    if not isinstance(raw, dict):
        raise InvalidPolicyError("policy must be an object")

    absolute_mins: list[AbsoluteMinRule] = []
    latency: LatencyP95Rule | None = None
    cost: CostMeanRule | None = None
    regression: RegressionRule | None = None
    experiment_metrics: tuple[ExperimentMetricRule, ...] = ()

    for key, value in raw.items():
        if key in META_KEYS:
            continue
        if not isinstance(value, dict):
            raise InvalidPolicyError(f"policy.{key} must be an object")
        if key == "regression":
            regression = _parse_regression(value)
            continue
        if key == EXPERIMENT_METRICS_KEY:
            experiment_metrics = _parse_experiment_metrics(value)
            continue
        if key == "latency":
            latency = _parse_latency(value)
            continue
        if key == "cost":
            cost = _parse_cost(value)
            continue
        absolute_mins.append(_parse_absolute_min(key, value))

    if (
        not absolute_mins
        and latency is None
        and cost is None
        and regression is None
        and not experiment_metrics
    ):
        raise InvalidPolicyError("policy must define at least one rule")

    return ReleasePolicy(
        absolute_mins=tuple(absolute_mins),
        latency=latency,
        cost=cost,
        regression=regression,
        experiment_metrics=experiment_metrics,
    )


def _require_float(block: str, field: str, value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise InvalidPolicyError(f"policy.{block}.{field} must be a number")
    return float(value)


def _parse_absolute_min(name: str, value: dict[str, Any]) -> AbsoluteMinRule:
    unknown = set(value) - _MIN_KEYS
    if unknown:
        raise InvalidPolicyError(f"policy.{name} has unsupported keys: {sorted(unknown)}")
    if "min" not in value:
        raise InvalidPolicyError(f"policy.{name} requires min")
    return AbsoluteMinRule(evaluator_name=name, min_score=_require_float(name, "min", value["min"]))


def _parse_latency(value: dict[str, Any]) -> LatencyP95Rule:
    unknown = set(value) - _LATENCY_KEYS
    if unknown:
        raise InvalidPolicyError(f"policy.latency has unsupported keys: {sorted(unknown)}")
    if "p95_max_ms" not in value:
        raise InvalidPolicyError("policy.latency requires p95_max_ms")
    return LatencyP95Rule(
        evaluator_name="latency",
        p95_max_ms=_require_float("latency", "p95_max_ms", value["p95_max_ms"]),
    )


def _parse_cost(value: dict[str, Any]) -> CostMeanRule:
    unknown = set(value) - _COST_KEYS
    if unknown:
        raise InvalidPolicyError(f"policy.cost has unsupported keys: {sorted(unknown)}")
    if "max_per_request_usd" not in value:
        raise InvalidPolicyError("policy.cost requires max_per_request_usd")
    return CostMeanRule(
        evaluator_name="cost",
        max_per_request_usd=_require_float(
            "cost", "max_per_request_usd", value["max_per_request_usd"]
        ),
    )


def _parse_regression(value: dict[str, Any]) -> RegressionRule:
    unknown = set(value) - _REGRESSION_KEYS
    if unknown:
        raise InvalidPolicyError(f"policy.regression has unsupported keys: {sorted(unknown)}")
    if "max_delta" not in value:
        raise InvalidPolicyError("policy.regression requires max_delta")
    allow = value.get("allow_insufficient_n", False)
    if not isinstance(allow, bool):
        raise InvalidPolicyError("policy.regression.allow_insufficient_n must be a boolean")
    return RegressionRule(
        max_delta=_require_float("regression", "max_delta", value["max_delta"]),
        allow_insufficient_n=allow,
    )


def _parse_experiment_metrics(value: dict[str, Any]) -> tuple[ExperimentMetricRule, ...]:
    rules: list[ExperimentMetricRule] = []
    for key, rule in value.items():
        block = f"{EXPERIMENT_METRICS_KEY}.{key}"
        if not METRIC_KEY_PATTERN.fullmatch(key):
            raise InvalidPolicyError(
                f"policy.{EXPERIMENT_METRICS_KEY} has invalid metric key {key!r}"
            )
        if not isinstance(rule, dict):
            raise InvalidPolicyError(f"policy.{block} must be an object")
        unknown = set(rule) - _EXPERIMENT_METRIC_KEYS
        if unknown:
            raise InvalidPolicyError(f"policy.{block} has unsupported keys: {sorted(unknown)}")
        if not rule:
            raise InvalidPolicyError(f"policy.{block} requires min or max")
        min_value = _require_float(block, "min", rule["min"]) if "min" in rule else None
        max_value = _require_float(block, "max", rule["max"]) if "max" in rule else None
        if min_value is not None and max_value is not None and min_value > max_value:
            raise InvalidPolicyError(f"policy.{block} min must be <= max")
        rules.append(ExperimentMetricRule(key=key, min_value=min_value, max_value=max_value))
    if not rules:
        raise InvalidPolicyError(f"policy.{EXPERIMENT_METRICS_KEY} must define at least one metric")
    return tuple(rules)


def percentile_nearest_rank(values: list[float], percentile: float) -> float:
    if not values:
        raise ValueError("values must be non-empty")
    if not 0.0 < percentile <= 100.0:
        raise ValueError("percentile must be in (0, 100]")
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile / 100.0 * len(ordered)))
    return ordered[rank - 1]


def _metadata_floats(
    results: tuple[EvaluationResultRecord, ...] | list[EvaluationResultRecord],
    key: str,
) -> list[float]:
    out: list[float] = []
    for result in results:
        raw = result.metadata.get(key)
        if raw is None:
            continue
        if isinstance(raw, bool) or not isinstance(raw, int | float):
            continue
        out.append(float(raw))
    return out


def _by_name(
    metrics: list[EvaluatorMetricInput] | tuple[EvaluatorMetricInput, ...],
) -> dict[str, EvaluatorMetricInput]:
    return {m.evaluator_name: m for m in metrics}


def evaluate_policy(
    policy: ReleasePolicy,
    *,
    candidate: list[EvaluatorMetricInput] | tuple[EvaluatorMetricInput, ...],
    regression_deltas: list[RegressionDeltaInput] | tuple[RegressionDeltaInput, ...] = (),
    experiment_metrics: Mapping[str, float] | None = None,
) -> PolicyEvaluation:
    checks: list[PolicyCheck] = []
    by_name = _by_name(candidate)

    for rule in policy.absolute_mins:
        metric = by_name.get(rule.evaluator_name)
        if metric is None or metric.mean_score is None:
            checks.append(
                PolicyCheck(
                    metric=f"{rule.evaluator_name}.min",
                    actual=None,
                    threshold=rule.min_score,
                    status="unavailable",
                )
            )
            continue
        actual = metric.mean_score
        checks.append(
            PolicyCheck(
                metric=f"{rule.evaluator_name}.min",
                actual=actual,
                threshold=rule.min_score,
                status="passed" if actual >= rule.min_score else "failed",
            )
        )

    if policy.latency is not None:
        checks.append(_eval_latency(policy.latency, by_name.get(policy.latency.evaluator_name)))

    if policy.cost is not None:
        checks.append(_eval_cost(policy.cost, by_name.get(policy.cost.evaluator_name)))

    for metric_rule in policy.experiment_metrics:
        checks.extend(
            _eval_experiment_metric(metric_rule, (experiment_metrics or {}).get(metric_rule.key))
        )

    if policy.regression is not None:
        if not regression_deltas:
            checks.append(
                PolicyCheck(
                    metric="regression.max_delta",
                    actual=None,
                    threshold=policy.regression.max_delta,
                    status="unavailable",
                )
            )
        else:
            for delta in regression_deltas:
                checks.append(_eval_regression(policy.regression, delta))

    overall: OverallStatus = (
        "passed" if checks and all(c.status == "passed" for c in checks) else "failed"
    )
    if not checks:
        overall = "failed"
    return PolicyEvaluation(status=overall, checks=tuple(checks))


def _usable_latency_ms(result: EvaluationResultRecord) -> float | None:
    raw = result.metadata.get("latency_ms")
    if raw is None or isinstance(raw, bool) or not isinstance(raw, int | float):
        return None
    return float(raw)


def _has_missing_output_without_latency(
    results: tuple[EvaluationResultRecord, ...] | list[EvaluationResultRecord],
) -> bool:
    for result in results:
        if result.metadata.get("missing_output") is True and _usable_latency_ms(result) is None:
            return True
    return False


def _eval_latency(
    rule: LatencyP95Rule,
    metric: EvaluatorMetricInput | None,
) -> PolicyCheck:
    if metric is None:
        return PolicyCheck(
            metric="latency.p95",
            actual=None,
            threshold=rule.p95_max_ms,
            status="unavailable",
        )
    # Missing app output is a quality failure for the latency gate: do not compute
    # p95 on the remaining subset alone (that would green-light incomplete runs).
    if _has_missing_output_without_latency(metric.results):
        values = _metadata_floats(metric.results, "latency_ms")
        actual = percentile_nearest_rank(values, 95.0) if values else None
        return PolicyCheck(
            metric="latency.p95",
            actual=actual,
            threshold=rule.p95_max_ms,
            status="failed",
        )
    values = _metadata_floats(metric.results, "latency_ms")
    if not values:
        return PolicyCheck(
            metric="latency.p95",
            actual=None,
            threshold=rule.p95_max_ms,
            status="unavailable",
        )
    actual = percentile_nearest_rank(values, 95.0)
    return PolicyCheck(
        metric="latency.p95",
        actual=actual,
        threshold=rule.p95_max_ms,
        status="passed" if actual <= rule.p95_max_ms else "failed",
    )


def _eval_cost(
    rule: CostMeanRule,
    metric: EvaluatorMetricInput | None,
) -> PolicyCheck:
    if metric is None:
        return PolicyCheck(
            metric="cost.max_per_request_usd",
            actual=None,
            threshold=rule.max_per_request_usd,
            status="unavailable",
        )
    values = _metadata_floats(metric.results, "cost_usd")
    if not values:
        return PolicyCheck(
            metric="cost.max_per_request_usd",
            actual=None,
            threshold=rule.max_per_request_usd,
            status="unavailable",
        )
    actual = sum(values) / len(values)
    return PolicyCheck(
        metric="cost.max_per_request_usd",
        actual=actual,
        threshold=rule.max_per_request_usd,
        status="passed" if actual <= rule.max_per_request_usd else "failed",
    )


def _eval_experiment_metric(rule: ExperimentMetricRule, actual: float | None) -> list[PolicyCheck]:
    checks: list[PolicyCheck] = []
    for bound, threshold in (("min", rule.min_value), ("max", rule.max_value)):
        if threshold is None:
            continue
        status: CheckStatus
        if actual is None:
            status = "unavailable"
        elif bound == "min":
            status = "passed" if actual >= threshold else "failed"
        else:
            status = "passed" if actual <= threshold else "failed"
        checks.append(
            PolicyCheck(
                metric=f"{EXPERIMENT_METRICS_KEY}.{rule.key}.{bound}",
                actual=actual,
                threshold=threshold,
                status=status,
            )
        )
    return checks


def _eval_regression(rule: RegressionRule, delta: RegressionDeltaInput) -> PolicyCheck:
    metric = f"regression.{delta.evaluator_name}.mean_score"
    if delta.insufficient_n:
        return PolicyCheck(
            metric=metric,
            actual=delta.mean_score_delta,
            threshold=rule.max_delta,
            status="unavailable",
        )
    if delta.mean_score_delta is None:
        return PolicyCheck(
            metric=metric,
            actual=None,
            threshold=rule.max_delta,
            status="unavailable",
        )
    actual = delta.mean_score_delta
    return PolicyCheck(
        metric=metric,
        actual=actual,
        threshold=rule.max_delta,
        status="passed" if actual >= rule.max_delta else "failed",
    )
