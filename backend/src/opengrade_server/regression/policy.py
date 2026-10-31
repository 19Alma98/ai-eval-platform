from __future__ import annotations

import math
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from opengrade_server.domain.evaluation import EvaluationResultRecord
from opengrade_server.domain.experiment_metric import METRIC_KEY_PATTERN

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

# Relative bounds compare the candidate with the baseline experiment.
INCREASE_PCT_KEY = "max_increase_pct"
_RELATIVE_METRIC_KEYS = frozenset(
    {"max_increase", "max_decrease", INCREASE_PCT_KEY, "max_decrease_pct"}
)
_LATENCY_KEYS = frozenset({"p95_max_ms", INCREASE_PCT_KEY})
_COST_KEYS = frozenset({"max_per_request_usd", INCREASE_PCT_KEY})
_MIN_KEYS = frozenset({"min"})
_REGRESSION_KEYS = frozenset({"max_delta", "allow_insufficient_n"})
_EXPERIMENT_METRIC_KEYS = frozenset({"min", "max"}) | _RELATIVE_METRIC_KEYS
_GROUP_KEYS = frozenset({"by", "min_items", "metrics", "max_delta"})
EXPERIMENT_METRICS_KEY = "experiment_metrics"
GROUPS_KEY = "groups"
DEFAULT_GROUP_MIN_ITEMS = 5


class InvalidPolicyError(ValueError):
    """Policy dict is malformed or uses unsupported keys."""


@dataclass(frozen=True, slots=True)
class AbsoluteMinRule:
    evaluator_name: str
    min_score: float


@dataclass(frozen=True, slots=True)
class LatencyP95Rule:
    """p95 latency: absolute ceiling and/or max % increase over the baseline p95."""

    evaluator_name: str
    p95_max_ms: float | None = None
    max_increase_pct: float | None = None


@dataclass(frozen=True, slots=True)
class CostMeanRule:
    """Mean cost per request: absolute ceiling and/or max % increase over the baseline."""

    evaluator_name: str
    max_per_request_usd: float | None = None
    max_increase_pct: float | None = None


@dataclass(frozen=True, slots=True)
class RegressionRule:
    max_delta: float | None = None
    allow_insufficient_n: bool = False


@dataclass(frozen=True, slots=True)
class ExperimentMetricRule:
    """Run-level metric bounds. ``max_increase`` / ``max_decrease`` are absolute changes vs
    the baseline run; the ``*_pct`` variants are relative to the baseline value."""

    key: str
    min_value: float | None = None
    max_value: float | None = None
    max_increase: float | None = None
    max_decrease: float | None = None
    max_increase_pct: float | None = None
    max_decrease_pct: float | None = None

    @property
    def is_relative(self) -> bool:
        return any(
            v is not None
            for v in (
                self.max_increase,
                self.max_decrease,
                self.max_increase_pct,
                self.max_decrease_pct,
            )
        )


@dataclass(frozen=True, slots=True)
class GroupRule:
    """Re-apply the min rules (and the regression bound) inside each group of items.

    Groups come from a dataset-item metadata field (``by``). Groups with fewer than
    ``min_items`` items are not gated. ``metrics`` limits which evaluators are checked;
    ``max_delta`` overrides ``regression.max_delta`` for groups.
    """

    by: str
    min_items: int = DEFAULT_GROUP_MIN_ITEMS
    metrics: tuple[str, ...] | None = None
    max_delta: float | None = None

    def applies_to(self, evaluator_name: str) -> bool:
        return self.metrics is None or evaluator_name in self.metrics


@dataclass(frozen=True, slots=True)
class ReleasePolicy:
    absolute_mins: tuple[AbsoluteMinRule, ...]
    latency: LatencyP95Rule | None
    cost: CostMeanRule | None
    regression: RegressionRule | None
    experiment_metrics: tuple[ExperimentMetricRule, ...] = ()
    groups: GroupRule | None = None

    def needs_baseline(self) -> bool:
        """True when any rule compares the candidate with a baseline experiment."""
        return (
            self.regression is not None
            or (self.groups is not None and self.groups.max_delta is not None)
            or (self.latency is not None and self.latency.max_increase_pct is not None)
            or (self.cost is not None and self.cost.max_increase_pct is not None)
            or any(rule.is_relative for rule in self.experiment_metrics)
        )

    def group_max_delta(self) -> float | None:
        if self.groups is None:
            return None
        if self.groups.max_delta is not None:
            return self.groups.max_delta
        return self.regression.max_delta if self.regression is not None else None


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
    compare_status: str | None = None


def strip_meta_keys(raw: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in raw.items() if k not in META_KEYS}


_NON_MIN_BLOCKS = frozenset({"regression", "latency", "cost", EXPERIMENT_METRICS_KEY, GROUPS_KEY})


def strip_baseline_rules(raw: dict[str, Any]) -> dict[str, Any]:
    """Raw policy without the rules that need a baseline: ``regression``,
    ``groups.max_delta`` and the relative latency / cost / run-metric bounds.

    Used when a run has no comparable baseline (first run of an alias, exam changed).
    Blocks left empty are dropped; ``groups`` is dropped when no metric ``min`` remains
    for it to re-apply.
    """
    out: dict[str, Any] = {}
    for key, value in raw.items():
        if key == "regression":
            continue
        if key in ("latency", "cost") and isinstance(value, dict):
            kept = {k: v for k, v in value.items() if k != INCREASE_PCT_KEY}
            if kept:
                out[key] = kept
            continue
        if key == EXPERIMENT_METRICS_KEY and isinstance(value, dict):
            metrics: dict[str, Any] = {}
            for metric_key, rule in value.items():
                if isinstance(rule, dict):
                    rule = {k: v for k, v in rule.items() if k not in _RELATIVE_METRIC_KEYS}
                    if not rule:
                        continue
                metrics[metric_key] = rule
            if metrics:
                out[key] = metrics
            continue
        if key == GROUPS_KEY and isinstance(value, dict):
            out[key] = {k: v for k, v in value.items() if k != "max_delta"}
            continue
        out[key] = value
    has_min_rules = any(k not in _NON_MIN_BLOCKS and k not in META_KEYS for k in out)
    if GROUPS_KEY in out and not has_min_rules:
        del out[GROUPS_KEY]
    return out


def parse_release_policy(raw: dict[str, Any]) -> ReleasePolicy:
    if not isinstance(raw, dict):
        raise InvalidPolicyError("policy must be an object")

    absolute_mins: list[AbsoluteMinRule] = []
    latency: LatencyP95Rule | None = None
    cost: CostMeanRule | None = None
    regression: RegressionRule | None = None
    experiment_metrics: tuple[ExperimentMetricRule, ...] = ()
    groups: GroupRule | None = None

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
        if key == GROUPS_KEY:
            groups = _parse_groups(value)
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

    policy = ReleasePolicy(
        absolute_mins=tuple(absolute_mins),
        latency=latency,
        cost=cost,
        regression=regression,
        experiment_metrics=experiment_metrics,
        groups=groups,
    )
    if (
        groups is not None
        and not absolute_mins
        and regression is None
        and policy.group_max_delta() is None
    ):
        raise InvalidPolicyError(
            "policy.groups needs metric min rules, a regression block, "
            "or groups.max_delta to apply per group"
        )
    return policy


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


def _optional_float(block: str, value: dict[str, Any], field: str) -> float | None:
    return _require_float(block, field, value[field]) if field in value else None


def _optional_non_negative(block: str, value: dict[str, Any], field: str) -> float | None:
    parsed = _optional_float(block, value, field)
    if parsed is not None and parsed < 0:
        raise InvalidPolicyError(f"policy.{block}.{field} must be >= 0")
    return parsed


def _parse_latency(value: dict[str, Any]) -> LatencyP95Rule:
    unknown = set(value) - _LATENCY_KEYS
    if unknown:
        raise InvalidPolicyError(f"policy.latency has unsupported keys: {sorted(unknown)}")
    if not value:
        raise InvalidPolicyError("policy.latency requires p95_max_ms or max_increase_pct")
    return LatencyP95Rule(
        evaluator_name="latency",
        p95_max_ms=_optional_float("latency", value, "p95_max_ms"),
        max_increase_pct=_optional_non_negative("latency", value, INCREASE_PCT_KEY),
    )


def _parse_cost(value: dict[str, Any]) -> CostMeanRule:
    unknown = set(value) - _COST_KEYS
    if unknown:
        raise InvalidPolicyError(f"policy.cost has unsupported keys: {sorted(unknown)}")
    if not value:
        raise InvalidPolicyError("policy.cost requires max_per_request_usd or max_increase_pct")
    return CostMeanRule(
        evaluator_name="cost",
        max_per_request_usd=_optional_float("cost", value, "max_per_request_usd"),
        max_increase_pct=_optional_non_negative("cost", value, INCREASE_PCT_KEY),
    )


def _parse_regression(value: dict[str, Any]) -> RegressionRule:
    unknown = set(value) - _REGRESSION_KEYS
    if unknown:
        raise InvalidPolicyError(f"policy.regression has unsupported keys: {sorted(unknown)}")
    allow = value.get("allow_insufficient_n", False)
    if not isinstance(allow, bool):
        raise InvalidPolicyError("policy.regression.allow_insufficient_n must be a boolean")
    max_delta = (
        _require_float("regression", "max_delta", value["max_delta"])
        if "max_delta" in value
        else None
    )
    return RegressionRule(max_delta=max_delta, allow_insufficient_n=allow)


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
            raise InvalidPolicyError(
                f"policy.{block} requires min or max, or a max_increase/max_decrease bound"
            )
        min_value = _optional_float(block, rule, "min")
        max_value = _optional_float(block, rule, "max")
        if min_value is not None and max_value is not None and min_value > max_value:
            raise InvalidPolicyError(f"policy.{block} min must be <= max")
        rules.append(
            ExperimentMetricRule(
                key=key,
                min_value=min_value,
                max_value=max_value,
                max_increase=_optional_non_negative(block, rule, "max_increase"),
                max_decrease=_optional_non_negative(block, rule, "max_decrease"),
                max_increase_pct=_optional_non_negative(block, rule, INCREASE_PCT_KEY),
                max_decrease_pct=_optional_non_negative(block, rule, "max_decrease_pct"),
            )
        )
    if not rules:
        raise InvalidPolicyError(f"policy.{EXPERIMENT_METRICS_KEY} must define at least one metric")
    return tuple(rules)


def _parse_groups(value: dict[str, Any]) -> GroupRule:
    unknown = set(value) - _GROUP_KEYS
    if unknown:
        raise InvalidPolicyError(f"policy.groups has unsupported keys: {sorted(unknown)}")
    by = value.get("by")
    if not isinstance(by, str) or not by.strip():
        raise InvalidPolicyError("policy.groups requires by (a dataset metadata field)")
    min_items = value.get("min_items", DEFAULT_GROUP_MIN_ITEMS)
    if isinstance(min_items, bool) or not isinstance(min_items, int) or min_items < 1:
        raise InvalidPolicyError("policy.groups.min_items must be a positive integer")
    metrics = value.get("metrics")
    if metrics is not None and (
        not isinstance(metrics, list)
        or not metrics
        or not all(isinstance(m, str) and m.strip() for m in metrics)
    ):
        raise InvalidPolicyError("policy.groups.metrics must be a non-empty list of names")
    max_delta = value.get("max_delta")
    return GroupRule(
        by=by.strip(),
        min_items=min_items,
        metrics=tuple(m.strip() for m in metrics) if metrics is not None else None,
        max_delta=_require_float("groups", "max_delta", max_delta)
        if max_delta is not None
        else None,
    )


@dataclass(frozen=True, slots=True)
class GroupInput:
    """One group of items: candidate means, mean-score deltas, and compare statuses."""

    value: str
    n_items: int
    mean_scores: Mapping[str, float | None]
    deltas: Mapping[str, float | None]
    statuses: Mapping[str, str] = field(default_factory=dict)


def evaluate_group_checks(policy: ReleasePolicy, groups: list[GroupInput]) -> list[PolicyCheck]:
    """Per-group min and regression checks. Metrics that do not apply to a group (no
    applicable item, no paired delta) and groups under ``min_items`` are not checked."""
    rule = policy.groups
    if rule is None:
        return []
    run_regression = policy.regression is not None or policy.group_max_delta() is not None
    floor = policy.group_max_delta()
    checks: list[PolicyCheck] = []
    for group in groups:
        if group.n_items < rule.min_items:
            continue
        prefix = f"{GROUPS_KEY}.{rule.by}={group.value}"
        for min_rule in policy.absolute_mins:
            if not rule.applies_to(min_rule.evaluator_name):
                continue
            actual = group.mean_scores.get(min_rule.evaluator_name)
            if actual is None:
                continue
            checks.append(
                PolicyCheck(
                    metric=f"{prefix}.{min_rule.evaluator_name}.min",
                    actual=actual,
                    threshold=min_rule.min_score,
                    status="passed" if actual >= min_rule.min_score else "failed",
                )
            )
        if not run_regression:
            continue
        names = sorted(
            set(group.deltas) | set(group.statuses),
            key=str,
        )
        for name in names:
            if not rule.applies_to(name):
                continue
            status = group.statuses.get(name)
            delta = group.deltas.get(name)
            if status is None and delta is None:
                continue
            if status == "insufficient_n":
                if policy.regression is not None and policy.regression.allow_insufficient_n:
                    continue
                checks.append(
                    PolicyCheck(
                        metric=f"{prefix}.regression.{name}.mean_score",
                        actual=delta,
                        threshold=floor,
                        status="unavailable",
                    )
                )
                continue
            if status in ("config_mismatch", "unavailable"):
                checks.append(
                    PolicyCheck(
                        metric=f"{prefix}.regression.{name}.mean_score",
                        actual=delta,
                        threshold=floor,
                        status="unavailable",
                    )
                )
                continue
            if status == "regression":
                checks.append(
                    PolicyCheck(
                        metric=f"{prefix}.regression.{name}.mean_score",
                        actual=delta,
                        threshold=floor,
                        status="failed",
                    )
                )
                continue
            if status in ("improved", "unchanged"):
                if floor is not None and delta is not None and delta < floor:
                    checks.append(
                        PolicyCheck(
                            metric=f"{prefix}.regression.{name}.mean_score",
                            actual=delta,
                            threshold=floor,
                            status="failed",
                        )
                    )
                else:
                    checks.append(
                        PolicyCheck(
                            metric=f"{prefix}.regression.{name}.mean_score",
                            actual=delta,
                            threshold=floor,
                            status="passed",
                        )
                    )
                continue
            if status is None and delta is not None and floor is not None:
                checks.append(
                    PolicyCheck(
                        metric=f"{prefix}.regression.{name}.mean_score",
                        actual=delta,
                        threshold=floor,
                        status="passed" if delta >= floor else "failed",
                    )
                )
    return checks


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
    groups: list[GroupInput] | None = None,
    baseline: list[EvaluatorMetricInput] | tuple[EvaluatorMetricInput, ...] | None = None,
    baseline_experiment_metrics: Mapping[str, float] | None = None,
) -> PolicyEvaluation:
    """Apply ``policy``. ``baseline`` / ``baseline_experiment_metrics`` feed the relative
    latency, cost and run-metric bounds (``max_increase_pct`` …); without them those
    checks are ``unavailable``."""
    checks: list[PolicyCheck] = []
    by_name = _by_name(candidate)
    base_by_name = _by_name(baseline or ())

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
        name = policy.latency.evaluator_name
        checks.extend(_eval_latency(policy.latency, by_name.get(name), base_by_name.get(name)))

    if policy.cost is not None:
        name = policy.cost.evaluator_name
        checks.extend(_eval_cost(policy.cost, by_name.get(name), base_by_name.get(name)))

    for metric_rule in policy.experiment_metrics:
        actual_value = (experiment_metrics or {}).get(metric_rule.key)
        checks.extend(_eval_experiment_metric(metric_rule, actual_value))
        if metric_rule.is_relative:
            checks.extend(
                _eval_experiment_metric_vs_baseline(
                    metric_rule,
                    actual_value,
                    (baseline_experiment_metrics or {}).get(metric_rule.key),
                )
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

    checks.extend(evaluate_group_checks(policy, groups or []))

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


def _latency_p95(metric: EvaluatorMetricInput | None) -> tuple[float | None, bool]:
    """``(p95, has_missing_output)``: an item without output and without latency counts
    as a failure for the absolute ceiling (it may have timed out)."""
    if metric is None:
        return None, False
    values = _metadata_floats(metric.results, "latency_ms")
    p95 = percentile_nearest_rank(values, 95.0) if values else None
    return p95, _has_missing_output_without_latency(metric.results)


def _cost_mean(metric: EvaluatorMetricInput | None) -> float | None:
    if metric is None:
        return None
    values = _metadata_floats(metric.results, "cost_usd")
    return sum(values) / len(values) if values else None


def percent_change(candidate: float, baseline: float) -> float | None:
    """Relative change in percent; ``None`` when the baseline is 0 and the candidate is not
    (an infinite increase)."""
    if baseline == 0:
        return 0.0 if candidate == 0 else None
    return (candidate - baseline) / abs(baseline) * 100.0


def _increase_pct_check(
    metric: str, candidate: float | None, baseline: float | None, max_pct: float
) -> PolicyCheck:
    if candidate is None or baseline is None:
        return PolicyCheck(metric=metric, actual=None, threshold=max_pct, status="unavailable")
    change = percent_change(candidate, baseline)
    if change is None:
        # Baseline was 0: any increase is unbounded in percent.
        return PolicyCheck(metric=metric, actual=None, threshold=max_pct, status="failed")
    return PolicyCheck(
        metric=metric,
        actual=change,
        threshold=max_pct,
        status="passed" if change <= max_pct else "failed",
    )


def _eval_latency(
    rule: LatencyP95Rule,
    metric: EvaluatorMetricInput | None,
    baseline: EvaluatorMetricInput | None = None,
) -> list[PolicyCheck]:
    checks: list[PolicyCheck] = []
    actual, missing_output = _latency_p95(metric)
    if rule.p95_max_ms is not None:
        status: CheckStatus
        if missing_output:
            status = "failed"
        elif actual is None:
            status = "unavailable"
        else:
            status = "passed" if actual <= rule.p95_max_ms else "failed"
        checks.append(
            PolicyCheck(
                metric="latency.p95", actual=actual, threshold=rule.p95_max_ms, status=status
            )
        )
    if rule.max_increase_pct is not None:
        base_p95, _ = _latency_p95(baseline)
        checks.append(
            _increase_pct_check(
                f"latency.p95.{INCREASE_PCT_KEY}", actual, base_p95, rule.max_increase_pct
            )
        )
    return checks


def _eval_cost(
    rule: CostMeanRule,
    metric: EvaluatorMetricInput | None,
    baseline: EvaluatorMetricInput | None = None,
) -> list[PolicyCheck]:
    checks: list[PolicyCheck] = []
    actual = _cost_mean(metric)
    if rule.max_per_request_usd is not None:
        status: CheckStatus = (
            "unavailable"
            if actual is None
            else "passed"
            if actual <= rule.max_per_request_usd
            else "failed"
        )
        checks.append(
            PolicyCheck(
                metric="cost.max_per_request_usd",
                actual=actual,
                threshold=rule.max_per_request_usd,
                status=status,
            )
        )
    if rule.max_increase_pct is not None:
        checks.append(
            _increase_pct_check(
                f"cost.mean_per_request_usd.{INCREASE_PCT_KEY}",
                actual,
                _cost_mean(baseline),
                rule.max_increase_pct,
            )
        )
    return checks


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


def _eval_experiment_metric_vs_baseline(
    rule: ExperimentMetricRule, actual: float | None, baseline: float | None
) -> list[PolicyCheck]:
    """Change vs the baseline run, reported in the direction the bound names (an increase
    for ``max_increase*``, a decrease for ``max_decrease*``); passes when <= threshold."""
    checks: list[PolicyCheck] = []
    prefix = f"{EXPERIMENT_METRICS_KEY}.{rule.key}"
    bounds = (
        ("max_increase", rule.max_increase, 1.0, False),
        ("max_decrease", rule.max_decrease, -1.0, False),
        (INCREASE_PCT_KEY, rule.max_increase_pct, 1.0, True),
        ("max_decrease_pct", rule.max_decrease_pct, -1.0, True),
    )
    for name, threshold, sign, relative in bounds:
        if threshold is None:
            continue
        metric = f"{prefix}.{name}"
        if actual is None or baseline is None:
            checks.append(
                PolicyCheck(metric=metric, actual=None, threshold=threshold, status="unavailable")
            )
            continue
        if relative:
            change = percent_change(actual, baseline)
            if change is None:
                # Baseline 0, candidate moved: unbounded in percent; fails only in the
                # direction the bound guards.
                moved_wrong_way = (actual - baseline) * sign > 0
                checks.append(
                    PolicyCheck(
                        metric=metric,
                        actual=None,
                        threshold=threshold,
                        status="failed" if moved_wrong_way else "passed",
                    )
                )
                continue
        else:
            change = actual - baseline
        moved = change * sign
        checks.append(
            PolicyCheck(
                metric=metric,
                actual=moved,
                threshold=threshold,
                status="passed" if moved <= threshold else "failed",
            )
        )
    return checks


def _eval_regression(rule: RegressionRule, delta: RegressionDeltaInput) -> PolicyCheck:
    """Gate on compare bootstrap status; optional ``max_delta`` is a mean floor."""
    metric = f"regression.{delta.evaluator_name}.mean_score"
    status = delta.compare_status
    if delta.insufficient_n or status == "insufficient_n":
        return PolicyCheck(
            metric=metric,
            actual=delta.mean_score_delta,
            threshold=rule.max_delta,
            status="unavailable",
        )
    if status in ("config_mismatch", "unavailable"):
        return PolicyCheck(
            metric=metric,
            actual=delta.mean_score_delta,
            threshold=rule.max_delta,
            status="unavailable",
        )
    if status == "regression":
        return PolicyCheck(
            metric=metric,
            actual=delta.mean_score_delta,
            threshold=rule.max_delta,
            status="failed",
        )
    if status in ("improved", "unchanged"):
        actual = delta.mean_score_delta
        if rule.max_delta is not None and actual is not None and actual < rule.max_delta:
            return PolicyCheck(
                metric=metric,
                actual=actual,
                threshold=rule.max_delta,
                status="failed",
            )
        return PolicyCheck(
            metric=metric,
            actual=actual,
            threshold=rule.max_delta,
            status="passed",
        )
    if delta.mean_score_delta is None:
        return PolicyCheck(
            metric=metric,
            actual=None,
            threshold=rule.max_delta,
            status="unavailable",
        )
    actual = delta.mean_score_delta
    if rule.max_delta is None:
        return PolicyCheck(
            metric=metric,
            actual=actual,
            threshold=None,
            status="unavailable",
        )
    return PolicyCheck(
        metric=metric,
        actual=actual,
        threshold=rule.max_delta,
        status="passed" if actual >= rule.max_delta else "failed",
    )
