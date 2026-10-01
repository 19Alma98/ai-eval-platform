from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from typing import Any, Literal

from aiobs.domain.evaluation import EvaluationResultRecord

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
_REGRESSION_KEYS = frozenset({"max_delta"})


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


@dataclass(frozen=True, slots=True)
class ReleasePolicy:
    absolute_mins: tuple[AbsoluteMinRule, ...]
    latency: LatencyP95Rule | None
    cost: CostMeanRule | None
    regression: RegressionRule | None


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


def strip_meta_keys(raw: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in raw.items() if k not in META_KEYS}


def parse_release_policy(raw: dict[str, Any]) -> ReleasePolicy:
    if not isinstance(raw, dict):
        raise InvalidPolicyError("policy must be an object")

    absolute_mins: list[AbsoluteMinRule] = []
    latency: LatencyP95Rule | None = None
    cost: CostMeanRule | None = None
    regression: RegressionRule | None = None

    for key, value in raw.items():
        if key in META_KEYS:
            continue
        if not isinstance(value, dict):
            raise InvalidPolicyError(f"policy.{key} must be an object")
        if key == "regression":
            regression = _parse_regression(value)
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
    ):
        raise InvalidPolicyError("policy must define at least one rule")

    return ReleasePolicy(
        absolute_mins=tuple(absolute_mins),
        latency=latency,
        cost=cost,
        regression=regression,
    )


def _require_float(block: str, field: str, value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise InvalidPolicyError(f"policy.{block}.{field} must be a number")
    return float(value)


def _parse_absolute_min(name: str, value: dict[str, Any]) -> AbsoluteMinRule:
    unknown = set(value) - _MIN_KEYS
    if unknown:
        raise InvalidPolicyError(
            f"policy.{name} has unsupported keys: {sorted(unknown)}"
        )
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
        raise InvalidPolicyError(
            f"policy.regression has unsupported keys: {sorted(unknown)}"
        )
    if "max_delta" not in value:
        raise InvalidPolicyError("policy.regression requires max_delta")
    return RegressionRule(max_delta=_require_float("regression", "max_delta", value["max_delta"]))


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


def _eval_regression(rule: RegressionRule, delta: RegressionDeltaInput) -> PolicyCheck:
    metric = f"regression.{delta.evaluator_name}.mean_score"
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
