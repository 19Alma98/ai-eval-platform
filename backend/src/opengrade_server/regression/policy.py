from __future__ import annotations

import math
import uuid
from collections.abc import Iterable, Mapping, Set
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
_REGRESSION_KEYS = frozenset(
    {"max_delta", "allow_insufficient_n", "max_new_failures", "max_detectable_delta"}
)
_CRITICAL_KEYS = frozenset({"by", "metrics", "max_failures"})
_EXPERIMENT_METRIC_KEYS = frozenset({"min", "max"}) | _RELATIVE_METRIC_KEYS
_GROUP_KEYS = frozenset({"by", "min_items", "metrics", "max_delta"})
EXPERIMENT_METRICS_KEY = "experiment_metrics"
GROUPS_KEY = "groups"
CRITICAL_KEY = "critical"
DEFAULT_GROUP_MIN_ITEMS = 5
DEFAULT_CRITICAL_KEY = "critical"
# Evaluators that measure speed / spend, not answer quality. Item-level rules
# (critical items, new failures) skip them unless they are named explicitly: one slow
# request on a shared CI runner should not count as a broken answer.
OPERATIONAL_EVALUATORS = frozenset({"latency", "cost", "token_usage"})
# Test cases listed per item-level check (report / JUnit / API); the count is complete.
MAX_CHECK_ITEMS = 20


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
    """Candidate vs baseline.

    ``max_delta``: mean floor next to the bootstrap verdict. ``max_new_failures``: test
    cases that passed on the baseline and fail now (per evaluator); an int applies to
    every quality evaluator, a mapping names evaluators. ``max_detectable_delta``: the
    test set must be large enough to detect a mean drop of this size (~80% power).
    """

    max_delta: float | None = None
    allow_insufficient_n: bool = False
    max_new_failures: int | Mapping[str, int] | None = None
    max_detectable_delta: float | None = None

    def new_failures_limit(self, evaluator_name: str) -> int | None:
        limit = self.max_new_failures
        if limit is None:
            return None
        if isinstance(limit, int):
            return None if evaluator_name in OPERATIONAL_EVALUATORS else limit
        return limit.get(evaluator_name)


@dataclass(frozen=True, slots=True)
class CriticalRule:
    """Must-pass test cases: items whose metadata ``by`` field is true.

    Each critical item must PASS every evaluator (``metrics`` narrows them) in every
    repeat; ``max_failures`` tolerates that many failing critical items per evaluator.
    Absolute: needs no baseline.
    """

    by: str = DEFAULT_CRITICAL_KEY
    metrics: tuple[str, ...] | None = None
    max_failures: int = 0

    def applies_to(self, evaluator_name: str) -> bool:
        if self.metrics is None:
            return evaluator_name not in OPERATIONAL_EVALUATORS
        return evaluator_name in self.metrics


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
    critical: CriticalRule | None = None

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
class CheckItem:
    """A test case behind an item-level check (critical failure, new failure)."""

    dataset_item_id: uuid.UUID
    input: str | None = None
    candidate_label: str | None = None
    baseline_label: str | None = None


@dataclass(frozen=True, slots=True)
class PolicyCheck:
    metric: str
    actual: float | None
    threshold: float | None
    status: CheckStatus
    # Item-level checks: the failing test cases (at most MAX_CHECK_ITEMS).
    items: tuple[CheckItem, ...] = ()


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
    n_paired: int | None = None
    min_detectable_delta: float | None = None


def strip_meta_keys(raw: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in raw.items() if k not in META_KEYS}


_NON_MIN_BLOCKS = frozenset(
    {"regression", "latency", "cost", EXPERIMENT_METRICS_KEY, GROUPS_KEY, CRITICAL_KEY}
)


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
    critical: CriticalRule | None = None

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
        if key == CRITICAL_KEY:
            critical = _parse_critical(value)
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
        and critical is None
    ):
        raise InvalidPolicyError("policy must define at least one rule")

    policy = ReleasePolicy(
        absolute_mins=tuple(absolute_mins),
        latency=latency,
        cost=cost,
        regression=regression,
        experiment_metrics=experiment_metrics,
        groups=groups,
        critical=critical,
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
    max_detectable = _optional_float("regression", value, "max_detectable_delta")
    if max_detectable is not None and max_detectable <= 0:
        raise InvalidPolicyError("policy.regression.max_detectable_delta must be > 0")
    return RegressionRule(
        max_delta=max_delta,
        allow_insufficient_n=allow,
        max_new_failures=_parse_new_failures(value.get("max_new_failures")),
        max_detectable_delta=max_detectable,
    )


def _require_count(block: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InvalidPolicyError(f"policy.{block} must be a non-negative integer")
    return value


def _parse_new_failures(value: Any) -> int | dict[str, int] | None:
    if value is None:
        return None
    block = "regression.max_new_failures"
    if isinstance(value, dict):
        if not value:
            raise InvalidPolicyError(f"policy.{block} must name at least one metric")
        out: dict[str, int] = {}
        for name, limit in value.items():
            if not isinstance(name, str) or not name.strip():
                raise InvalidPolicyError(f"policy.{block} keys must be metric names")
            out[name.strip()] = _require_count(f"{block}.{name}", limit)
        return out
    return _require_count(block, value)


def _parse_names(block: str, value: Any) -> tuple[str, ...] | None:
    if value is None:
        return None
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(m, str) and m.strip() for m in value)
    ):
        raise InvalidPolicyError(f"policy.{block} must be a non-empty list of names")
    return tuple(m.strip() for m in value)


def _parse_critical(value: dict[str, Any]) -> CriticalRule:
    unknown = set(value) - _CRITICAL_KEYS
    if unknown:
        raise InvalidPolicyError(f"policy.critical has unsupported keys: {sorted(unknown)}")
    by = value.get("by", DEFAULT_CRITICAL_KEY)
    if not isinstance(by, str) or not by.strip():
        raise InvalidPolicyError("policy.critical.by must be a dataset metadata field")
    return CriticalRule(
        by=by.strip(),
        metrics=_parse_names("critical.metrics", value.get("metrics")),
        max_failures=_require_count("critical.max_failures", value.get("max_failures", 0)),
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
    critical_item_ids: Set[uuid.UUID] | None = None,
    item_inputs: Mapping[uuid.UUID, str | None] | None = None,
) -> PolicyEvaluation:
    """Apply ``policy``. ``baseline`` / ``baseline_experiment_metrics`` feed the relative
    latency, cost and run-metric bounds (``max_increase_pct`` …) and the new-failure
    count; without them those checks are ``unavailable``. ``critical_item_ids`` are the
    dataset items marked critical, ``item_inputs`` label the failing test cases."""
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
            if policy.regression.max_detectable_delta is not None:
                checks.extend(
                    _eval_detectable_delta(policy.regression.max_detectable_delta, delta)
                    for delta in regression_deltas
                    if delta.evaluator_name not in OPERATIONAL_EVALUATORS
                )
        if policy.regression.max_new_failures is not None:
            checks.extend(
                evaluate_new_failures(
                    policy.regression,
                    candidate=candidate,
                    baseline=baseline or (),
                    regression_deltas=regression_deltas,
                    item_inputs=item_inputs or {},
                )
            )

    if policy.critical is not None:
        checks.extend(
            evaluate_critical_checks(
                policy.critical,
                candidate=candidate,
                critical_item_ids=critical_item_ids,
                item_inputs=item_inputs or {},
            )
        )

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


def _label(result: EvaluationResultRecord) -> str:
    return (result.label or "").strip().upper()


def _item_rows(
    results: Iterable[EvaluationResultRecord],
) -> dict[uuid.UUID, list[EvaluationResultRecord]]:
    """Applicable (non-SKIPPED) results per dataset item, all repeats."""
    by_item: dict[uuid.UUID, list[EvaluationResultRecord]] = {}
    for result in results:
        if _label(result) == "SKIPPED":
            continue
        by_item.setdefault(result.dataset_item_id, []).append(result)
    return by_item


def _majority_pass(rows: list[EvaluationResultRecord]) -> bool:
    """Item verdict over its repeats, as in the compare page: PASS when half pass."""
    return sum(1 for r in rows if _label(r) == "PASS") * 2 >= len(rows)


def _verdict(rows: list[EvaluationResultRecord]) -> str:
    labels = {_label(r) for r in rows}
    if labels == {"PASS"}:
        return "PASS"
    if len(rows) > 1:
        passed = sum(1 for r in rows if _label(r) == "PASS")
        return f"FAIL ({passed}/{len(rows)} PASS)" if passed else "FAIL"
    return next(iter(labels)) or "FAIL"


def _item_order(item_id: uuid.UUID) -> str:
    return str(item_id)


def evaluate_critical_checks(
    rule: CriticalRule,
    *,
    candidate: list[EvaluatorMetricInput] | tuple[EvaluatorMetricInput, ...],
    critical_item_ids: Set[uuid.UUID] | None,
    item_inputs: Mapping[uuid.UUID, str | None],
) -> list[PolicyCheck]:
    """``critical.<metric>.failures``: critical items that did not PASS, per evaluator.

    Strict: with repeats every applicable repeat must PASS (a critical answer that is
    right two times out of three is not reliable). A dataset without critical items, or
    a named metric the run did not score, is ``unavailable`` (fails the gate) so a typo
    in ``by`` / ``metrics`` cannot pass silently.
    """
    threshold = float(rule.max_failures)
    if not critical_item_ids:
        return [
            PolicyCheck(
                metric=f"{CRITICAL_KEY}.{rule.by}.items",
                actual=0.0,
                threshold=None,
                status="unavailable",
            )
        ]
    checks: list[PolicyCheck] = []
    by_name = _by_name(candidate)
    names = list(rule.metrics) if rule.metrics is not None else sorted(by_name)
    for name in names:
        if not rule.applies_to(name):
            continue
        metric = by_name.get(name)
        if metric is None:
            checks.append(
                PolicyCheck(
                    metric=f"{CRITICAL_KEY}.{name}.failures",
                    actual=None,
                    threshold=threshold,
                    status="unavailable",
                )
            )
            continue
        rows = _item_rows(r for r in metric.results if r.dataset_item_id in critical_item_ids)
        if not rows:
            continue  # metric does not apply to any critical item (all SKIPPED)
        failing = [
            CheckItem(
                dataset_item_id=item_id,
                input=item_inputs.get(item_id),
                candidate_label=_verdict(item_rows),
            )
            for item_id, item_rows in sorted(rows.items(), key=lambda kv: _item_order(kv[0]))
            if any(_label(r) != "PASS" for r in item_rows)
        ]
        checks.append(
            PolicyCheck(
                metric=f"{CRITICAL_KEY}.{name}.failures",
                actual=float(len(failing)),
                threshold=threshold,
                status="passed" if len(failing) <= rule.max_failures else "failed",
                items=tuple(failing[:MAX_CHECK_ITEMS]),
            )
        )
    if not checks:
        checks.append(
            PolicyCheck(
                metric=f"{CRITICAL_KEY}.{rule.by}.items",
                actual=float(len(critical_item_ids)),
                threshold=None,
                status="unavailable",
            )
        )
    return checks


def evaluate_new_failures(
    rule: RegressionRule,
    *,
    candidate: list[EvaluatorMetricInput] | tuple[EvaluatorMetricInput, ...],
    baseline: list[EvaluatorMetricInput] | tuple[EvaluatorMetricInput, ...],
    regression_deltas: list[RegressionDeltaInput] | tuple[RegressionDeltaInput, ...],
    item_inputs: Mapping[uuid.UUID, str | None],
) -> list[PolicyCheck]:
    """``regression.<metric>.new_failures``: items PASS on the baseline, not PASS now.

    Item verdicts use the majority of repeats on both sides, like the compare page.
    Items SKIPPED on either side do not count. Evaluators the compare marked as not
    comparable (``config_mismatch``) are ``unavailable``.
    """
    cand_by_name = _by_name(candidate)
    base_by_name = _by_name(baseline)
    status_by_name = {d.evaluator_name: d.compare_status for d in regression_deltas}
    names: list[str]
    if isinstance(rule.max_new_failures, Mapping):
        names = list(rule.max_new_failures)
    else:
        names = sorted(set(cand_by_name) | set(base_by_name))
    checks: list[PolicyCheck] = []
    for name in names:
        limit = rule.new_failures_limit(name)
        if limit is None:
            continue
        metric_id = f"regression.{name}.new_failures"
        cand = cand_by_name.get(name)
        base = base_by_name.get(name)
        if (
            cand is None
            or base is None
            or status_by_name.get(name) in ("config_mismatch", "unavailable")
        ):
            checks.append(
                PolicyCheck(
                    metric=metric_id, actual=None, threshold=float(limit), status="unavailable"
                )
            )
            continue
        cand_rows = _item_rows(cand.results)
        base_rows = _item_rows(base.results)
        failing: list[CheckItem] = []
        for item_id in sorted(set(cand_rows) & set(base_rows), key=_item_order):
            if _majority_pass(base_rows[item_id]) and not _majority_pass(cand_rows[item_id]):
                failing.append(
                    CheckItem(
                        dataset_item_id=item_id,
                        input=item_inputs.get(item_id),
                        candidate_label=_verdict(cand_rows[item_id]),
                        baseline_label=_verdict(base_rows[item_id]),
                    )
                )
        checks.append(
            PolicyCheck(
                metric=metric_id,
                actual=float(len(failing)),
                threshold=float(limit),
                status="passed" if len(failing) <= limit else "failed",
                items=tuple(failing[:MAX_CHECK_ITEMS]),
            )
        )
    return checks


def _eval_detectable_delta(max_mde: float, delta: RegressionDeltaInput) -> PolicyCheck:
    """``regression.<metric>.min_detectable_delta``: is the test set large enough to see
    a mean drop of ``max_mde``? Unavailable when the compare could not pair the runs."""
    metric = f"regression.{delta.evaluator_name}.min_detectable_delta"
    mde = delta.min_detectable_delta
    if mde is None or delta.compare_status in ("config_mismatch", "unavailable"):
        return PolicyCheck(metric=metric, actual=mde, threshold=max_mde, status="unavailable")
    return PolicyCheck(
        metric=metric,
        actual=mde,
        threshold=max_mde,
        status="passed" if mde <= max_mde else "failed",
    )
