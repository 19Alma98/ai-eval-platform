"""Item-level gate rules: critical (must-pass) test cases, new failures vs the baseline,
and the minimum detectable drop of the paired comparison."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import pytest

from opengrade_server.api.schemas import ReleasePolicyBody
from opengrade_server.domain.evaluation import EvaluationResultRecord
from opengrade_server.regression.aggregate import (
    Aggregates,
    compare_evaluator_metrics,
    items_needed,
)
from opengrade_server.regression.aggregate import min_detectable_delta as mde
from opengrade_server.regression.policy import (
    EvaluatorMetricInput,
    InvalidPolicyError,
    RegressionDeltaInput,
    evaluate_policy,
    parse_release_policy,
    strip_baseline_rules,
)

ITEMS = [uuid.uuid4() for _ in range(6)]
INPUTS = {item: f"question {n}" for n, item in enumerate(ITEMS)}


def _metric(name: str, labels: Sequence[str | Sequence[str]]) -> EvaluatorMetricInput:
    """One evaluator's results: ``labels[i]`` for ``ITEMS[i]`` (a list = repeats)."""
    run_id = uuid.uuid4()
    rows: list[EvaluationResultRecord] = []
    for item, label in zip(ITEMS, labels, strict=False):
        repeats = [label] if isinstance(label, str) else list(label)
        for repeat, value in enumerate(repeats):
            rows.append(
                EvaluationResultRecord.create(
                    run_id,
                    item,
                    score=1.0 if value == "PASS" else 0.0,
                    label=value,
                    repeat=repeat,
                )
            )
    mean = sum(r.score or 0.0 for r in rows) / len(rows)
    return EvaluatorMetricInput(
        evaluator_id=uuid.uuid4(), evaluator_name=name, mean_score=mean, results=tuple(rows)
    )


def _by_metric(result: object) -> dict[str, object]:
    return {c.metric: c for c in result.checks}  # type: ignore[attr-defined]


# ---- parsing ---------------------------------------------------------------------------


def test_parse_critical_defaults_and_validation() -> None:
    policy = parse_release_policy({"critical": {}})
    assert policy.critical is not None
    assert policy.critical.by == "critical"
    assert policy.critical.max_failures == 0
    assert not policy.needs_baseline()

    custom = parse_release_policy(
        {"critical": {"by": "meta.must_pass", "metrics": ["must_contain"], "max_failures": 1}}
    )
    assert custom.critical is not None
    assert custom.critical.metrics == ("must_contain",)
    assert custom.critical.applies_to("must_contain")
    assert not custom.critical.applies_to("hit_at_k")

    for bad in (
        {"critical": {"by": ""}},
        {"critical": {"max_failures": -1}},
        {"critical": {"max_failures": True}},
        {"critical": {"metrics": []}},
        {"critical": {"nope": 1}},
    ):
        with pytest.raises(InvalidPolicyError):
            parse_release_policy(bad)


def test_parse_regression_new_failures_and_detectable_delta() -> None:
    policy = parse_release_policy({"regression": {"max_new_failures": 0}})
    assert policy.regression is not None
    assert policy.regression.new_failures_limit("hit_at_k") == 0
    assert policy.regression.new_failures_limit("latency") is None  # operational: skipped

    named = parse_release_policy(
        {"regression": {"max_new_failures": {"latency": 2}, "max_detectable_delta": 0.1}}
    )
    assert named.regression is not None
    assert named.regression.new_failures_limit("latency") == 2
    assert named.regression.new_failures_limit("hit_at_k") is None
    assert named.regression.max_detectable_delta == 0.1

    for bad in (
        {"regression": {"max_new_failures": -1}},
        {"regression": {"max_new_failures": 0.5}},
        {"regression": {"max_new_failures": {}}},
        {"regression": {"max_new_failures": {"hit_at_k": -2}}},
        {"regression": {"max_detectable_delta": 0}},
    ):
        with pytest.raises(InvalidPolicyError):
            parse_release_policy(bad)


def test_api_body_accepts_new_blocks() -> None:
    body = ReleasePolicyBody.model_validate(
        {
            "critical": {"metrics": ["hit_at_k"]},
            "regression": {"max_new_failures": {"hit_at_k": 0}, "max_detectable_delta": 0.2},
        }
    )
    raw = body.to_raw_dict()
    assert raw["critical"] == {"by": "critical", "metrics": ["hit_at_k"], "max_failures": 0}
    assert parse_release_policy(raw).regression is not None
    with pytest.raises(ValueError):
        ReleasePolicyBody.model_validate({"regression": {"max_new_failures": -1}})


def test_critical_is_kept_without_a_baseline() -> None:
    raw = {"critical": {}, "regression": {"max_new_failures": 0}}
    assert strip_baseline_rules(raw) == {"critical": {}}


# ---- critical items --------------------------------------------------------------------


def test_critical_items_must_pass_every_quality_metric() -> None:
    policy = parse_release_policy({"critical": {}})
    critical = {ITEMS[0], ITEMS[1]}
    candidate = [
        _metric("hit_at_k", ["PASS", "FAIL", "FAIL", "PASS", "PASS", "PASS"]),
        _metric("must_contain", ["PASS", "PASS", "FAIL", "FAIL", "PASS", "PASS"]),
        _metric("latency", ["FAIL"] * 6),  # operational: not part of critical by default
    ]
    result = evaluate_policy(
        policy, candidate=candidate, critical_item_ids=critical, item_inputs=INPUTS
    )
    checks = _by_metric(result)
    assert set(checks) == {"critical.hit_at_k.failures", "critical.must_contain.failures"}
    hit = checks["critical.hit_at_k.failures"]
    assert (hit.actual, hit.threshold, hit.status) == (1.0, 0.0, "failed")  # type: ignore[attr-defined]
    assert [i.input for i in hit.items] == ["question 1"]  # type: ignore[attr-defined]
    assert checks["critical.must_contain.failures"].status == "passed"  # type: ignore[attr-defined]
    assert result.status == "failed"

    tolerant = parse_release_policy({"critical": {"max_failures": 1}})
    assert (
        evaluate_policy(tolerant, candidate=candidate, critical_item_ids=critical).status
        == "passed"
    )


def test_critical_items_fail_on_any_failing_repeat() -> None:
    policy = parse_release_policy({"critical": {}})
    candidate = [_metric("hit_at_k", [["PASS", "PASS", "FAIL"], "FAIL"])]
    result = evaluate_policy(policy, candidate=candidate, critical_item_ids={ITEMS[0]})
    (check,) = result.checks
    assert check.status == "failed"
    assert check.items[0].candidate_label == "FAIL (2/3 PASS)"


def test_critical_without_marked_items_or_unknown_metric_is_unavailable() -> None:
    candidate = [_metric("hit_at_k", ["PASS"] * 6)]
    none = evaluate_policy(
        parse_release_policy({"critical": {}}), candidate=candidate, critical_item_ids=set()
    )
    assert [(c.metric, c.status) for c in none.checks] == [
        ("critical.critical.items", "unavailable")
    ]
    assert none.status == "failed"

    typo = evaluate_policy(
        parse_release_policy({"critical": {"metrics": ["hit_at_kk"]}}),
        candidate=candidate,
        critical_item_ids={ITEMS[0]},
    )
    assert [(c.metric, c.status) for c in typo.checks] == [
        ("critical.hit_at_kk.failures", "unavailable")
    ]


def test_critical_ignores_skipped_items() -> None:
    candidate = [_metric("hit_at_k", ["SKIPPED", "PASS"])]
    result = evaluate_policy(
        parse_release_policy({"critical": {}}),
        candidate=candidate,
        critical_item_ids={ITEMS[0], ITEMS[1]},
    )
    (check,) = result.checks
    assert (check.actual, check.status) == (0.0, "passed")


# ---- new failures vs baseline ----------------------------------------------------------


def _delta(
    name: str, status: str = "unchanged", mde_value: float | None = None
) -> RegressionDeltaInput:
    return RegressionDeltaInput(
        evaluator_name=name,
        mean_score_delta=0.0,
        compare_status=status,
        n_paired=6,
        min_detectable_delta=mde_value,
    )


def test_new_failures_count_pass_to_fail_flips() -> None:
    policy = parse_release_policy({"regression": {"max_new_failures": 0}})
    baseline = [_metric("hit_at_k", ["PASS", "PASS", "FAIL", "PASS", "PASS", "SKIPPED"])]
    # item 1 flips PASS→FAIL, item 2 FAIL→PASS (improvement), item 5 skipped on baseline.
    candidate = [_metric("hit_at_k", ["PASS", "FAIL", "PASS", "PASS", "PASS", "FAIL"])]
    result = evaluate_policy(
        policy,
        candidate=candidate,
        baseline=baseline,
        regression_deltas=[_delta("hit_at_k")],
        item_inputs=INPUTS,
    )
    check = _by_metric(result)["regression.hit_at_k.new_failures"]
    assert (check.actual, check.threshold, check.status) == (1.0, 0.0, "failed")  # type: ignore[attr-defined]
    (item,) = check.items  # type: ignore[attr-defined]
    assert (item.input, item.baseline_label, item.candidate_label) == ("question 1", "PASS", "FAIL")
    # The aggregate bootstrap check alone passes: the mean did not move.
    assert _by_metric(result)["regression.hit_at_k.mean_score"].status == "passed"  # type: ignore[attr-defined]
    assert result.status == "failed"


def test_new_failures_use_majority_of_repeats_and_skip_mismatched_configs() -> None:
    policy = parse_release_policy({"regression": {"max_new_failures": 0}})
    baseline = [_metric("hit_at_k", [["PASS", "PASS"], "PASS"]), _metric("judge", ["PASS"])]
    candidate = [
        _metric("hit_at_k", [["PASS", "FAIL"], ["FAIL", "FAIL", "PASS"]]),
        _metric("judge", ["FAIL"]),
    ]
    result = evaluate_policy(
        policy,
        candidate=candidate,
        baseline=baseline,
        regression_deltas=[_delta("hit_at_k"), _delta("judge", "config_mismatch")],
    )
    checks = _by_metric(result)
    hit = checks["regression.hit_at_k.new_failures"]
    # 1/2 PASS still counts as PASS (majority, as on the compare page); 1/3 does not.
    assert hit.actual == 1.0  # type: ignore[attr-defined]
    assert hit.items[0].candidate_label == "FAIL (1/3 PASS)"  # type: ignore[attr-defined]
    assert checks["regression.judge.new_failures"].status == "unavailable"  # type: ignore[attr-defined]


# ---- minimum detectable delta ----------------------------------------------------------


def test_min_detectable_delta_shrinks_with_items_and_grows_with_noise() -> None:
    # No run-to-run noise: z² / (n + z²), the share of test cases that must flip.
    assert mde([0.0] * 24) == pytest.approx(7.849 / (24 + 7.849), rel=1e-3)
    assert mde([0.0] * 100) == pytest.approx(0.0728, abs=1e-3)
    assert mde([0.0] * 4) is None  # under MIN_APPLICABLE_ITEMS
    noisy = mde([0.3, -0.3] * 12)
    assert noisy is not None and noisy > mde([0.0] * 24)  # type: ignore[operator]
    many = mde([0.3, -0.3] * 200)
    assert many is not None and many < 0.1
    # A real regression (4 of 20 cases flip) is not counted as noise.
    regressed = mde([-1.0] * 4 + [0.0] * 16)
    assert regressed is not None and regressed < 0.3
    assert regressed == pytest.approx(mde([0.0] * 20), abs=0.03)
    # Inverse: test cases needed for a target drop.
    assert items_needed(mde([0.0] * 24), 24, 0.05) == 150  # type: ignore[arg-type]
    assert items_needed(noisy, 24, 0.15) == 78
    assert items_needed(0.1, 0, 0.05) is None


def test_compare_reports_min_detectable_delta() -> None:
    base = _metric("hit_at_k", ["PASS"] * 6)
    cand = _metric("hit_at_k", ["PASS"] * 5 + ["FAIL"])
    agg = Aggregates(
        n_items=6,
        n_scored=6,
        n_error=0,
        n_skipped=0,
        n_applicable=6,
        mean_score=1.0,
        pass_rate=1.0,
    )
    rows = compare_evaluator_metrics(
        evaluator_id=base.evaluator_id,
        evaluator_name="hit_at_k",
        candidate=agg,
        baseline=agg,
        candidate_results=cand.results,
        baseline_results=base.results,
    )
    mean_row = next(r for r in rows if r.metric == "mean_score")
    assert mean_row.n_paired == 6
    assert mean_row.min_detectable_delta is not None
    assert mean_row.min_detectable_delta > 0.3  # 6 items cannot see a small drop


def test_max_detectable_delta_check() -> None:
    policy = parse_release_policy({"regression": {"max_detectable_delta": 0.1}})
    candidate = [_metric("hit_at_k", ["PASS"] * 6), _metric("latency", ["PASS"] * 6)]
    result = evaluate_policy(
        policy,
        candidate=candidate,
        regression_deltas=[
            _delta("hit_at_k", mde_value=0.31),
            _delta("must_contain", mde_value=0.05),
            _delta("judge", "config_mismatch", mde_value=None),
            _delta("latency", mde_value=0.9),  # operational: not checked
        ],
    )
    checks = _by_metric(result)
    assert checks["regression.hit_at_k.min_detectable_delta"].status == "failed"  # type: ignore[attr-defined]
    assert checks["regression.must_contain.min_detectable_delta"].status == "passed"  # type: ignore[attr-defined]
    assert checks["regression.judge.min_detectable_delta"].status == "unavailable"  # type: ignore[attr-defined]
    assert "regression.latency.min_detectable_delta" not in checks
