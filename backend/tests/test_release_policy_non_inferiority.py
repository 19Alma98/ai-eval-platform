"""``regression.non_inferiority_margin``: the candidate must be *shown* to be at most
``margin`` worse than the baseline (lower bound of the 95% paired bootstrap CI)."""

from __future__ import annotations

import uuid

import pytest

from opengrade_server.api.schemas import ReleasePolicyBody
from opengrade_server.cli_evaluate import detectable_delta_target, power_notes
from opengrade_server.cli_report import render_junit, render_markdown
from opengrade_server.domain.evaluation import EvaluationResultRecord
from opengrade_server.regression.aggregate import (
    aggregate_results,
    compare_evaluator_metrics,
)
from opengrade_server.regression.bootstrap import paired_mean_ci
from opengrade_server.regression.policy import (
    EvaluatorMetricInput,
    InvalidPolicyError,
    RegressionDeltaInput,
    evaluate_policy,
    parse_release_policy,
)


def _results(items: list[uuid.UUID], failing: set[int]) -> list[EvaluationResultRecord]:
    run_id = uuid.uuid4()
    return [
        EvaluationResultRecord.create(
            run_id,
            item,
            score=0.0 if n in failing else 1.0,
            label="FAIL" if n in failing else "PASS",
        )
        for n, item in enumerate(items)
    ]


def _gate(
    n: int,
    *,
    baseline_failing: set[int],
    candidate_failing: set[int],
    policy: dict[str, object],
) -> dict[str, object]:
    """Compare two runs of one evaluator on ``n`` items and apply ``policy``."""
    items = [uuid.uuid4() for _ in range(n)]
    base = _results(items, baseline_failing)
    cand = _results(items, candidate_failing)
    rows = compare_evaluator_metrics(
        evaluator_id=uuid.uuid4(),
        evaluator_name="hit_at_k",
        candidate=aggregate_results(cand),
        baseline=aggregate_results(base),
        candidate_results=cand,
        baseline_results=base,
        seed=11,
    )
    row = next(r for r in rows if r.metric == "mean_score")
    candidate = EvaluatorMetricInput(
        evaluator_id=row.evaluator_id,
        evaluator_name="hit_at_k",
        mean_score=row.candidate,
        results=tuple(cand),
    )
    result = evaluate_policy(
        parse_release_policy(policy),
        candidate=[candidate],
        regression_deltas=[
            RegressionDeltaInput(
                evaluator_name="hit_at_k",
                mean_score_delta=row.delta,
                compare_status=row.status,
                n_paired=row.n_paired,
                min_detectable_delta=row.min_detectable_delta,
                ci_low=row.ci_low,
            )
        ],
    )
    return {"status": result.status, "row": row, **{c.metric: c for c in result.checks}}


# ---- parsing ---------------------------------------------------------------------------


def test_parse_margin_and_validation() -> None:
    policy = parse_release_policy({"regression": {"non_inferiority_margin": 0.03}})
    assert policy.regression is not None
    assert policy.regression.non_inferiority_margin == 0.03
    assert policy.needs_baseline()
    for bad in (0, -0.1, 1, 1.5, "x"):
        with pytest.raises(InvalidPolicyError):
            parse_release_policy({"regression": {"non_inferiority_margin": bad}})
    body = ReleasePolicyBody.model_validate({"regression": {"non_inferiority_margin": 0.05}})
    assert body.regression is not None
    assert body.regression.non_inferiority_margin == 0.05


# ---- the CI behind the check -----------------------------------------------------------


def test_constant_diffs_give_a_point_ci() -> None:
    assert paired_mean_ci([0.0] * 30, seed=1) == (0.0, 0.0)
    assert paired_mean_ci([-0.5] * 8, seed=1) == (-0.5, -0.5)


def test_compare_reports_the_ci_for_unchanged_metrics() -> None:
    gate = _gate(20, baseline_failing=set(), candidate_failing=set(), policy={"regression": {}})
    row = gate["row"]
    assert row.status == "unchanged"  # type: ignore[attr-defined]
    assert (row.ci_low, row.ci_high) == (0.0, 0.0)  # type: ignore[attr-defined]


# ---- the gate --------------------------------------------------------------------------


def test_unchanged_deterministic_run_is_non_inferior() -> None:
    gate = _gate(
        20,
        baseline_failing={3},
        candidate_failing={3},
        policy={"regression": {"non_inferiority_margin": 0.03}},
    )
    check = gate["regression.hit_at_k.non_inferiority"]
    assert check.status == "passed"  # type: ignore[attr-defined]
    assert check.actual == 0.0  # type: ignore[attr-defined]
    assert check.threshold == -0.03  # type: ignore[attr-defined]
    assert gate["status"] == "passed"


def test_small_test_set_drop_passes_bootstrap_but_fails_non_inferiority() -> None:
    # One question of 20 breaks (-0.05): not significant and above max_delta, so the
    # default regression check passes. Non-inferiority cannot be shown: CI ~ [-0.15, 0].
    default = _gate(
        20,
        baseline_failing=set(),
        candidate_failing={0},
        policy={"regression": {"max_delta": -0.10}},
    )
    assert default["regression.hit_at_k.mean_score"].status == "passed"  # type: ignore[attr-defined]
    assert default["status"] == "passed"

    strict = _gate(
        20,
        baseline_failing=set(),
        candidate_failing={0},
        policy={"regression": {"max_delta": -0.10, "non_inferiority_margin": 0.03}},
    )
    assert strict["regression.hit_at_k.mean_score"].status == "passed"  # type: ignore[attr-defined]
    check = strict["regression.hit_at_k.non_inferiority"]
    assert check.status == "failed"  # type: ignore[attr-defined]
    assert check.actual < -0.03  # type: ignore[attr-defined]
    assert strict["status"] == "failed"


def test_large_test_set_small_drop_is_within_margin() -> None:
    # 1 of 400 breaks: the CI lower bound stays well inside a 0.03 margin.
    gate = _gate(
        400,
        baseline_failing=set(),
        candidate_failing={7},
        policy={"regression": {"non_inferiority_margin": 0.03}},
    )
    assert gate["regression.hit_at_k.non_inferiority"].status == "passed"  # type: ignore[attr-defined]
    assert gate["status"] == "passed"


def test_improvement_passes() -> None:
    gate = _gate(
        20,
        baseline_failing={0, 1, 2},
        candidate_failing=set(),
        policy={"regression": {"non_inferiority_margin": 0.03}},
    )
    assert gate["regression.hit_at_k.non_inferiority"].status == "passed"  # type: ignore[attr-defined]
    assert gate["regression.hit_at_k.mean_score"].status == "passed"  # type: ignore[attr-defined]


def test_unpaired_or_operational_metrics() -> None:
    policy = parse_release_policy({"regression": {"non_inferiority_margin": 0.05}})
    result = evaluate_policy(
        policy,
        candidate=[],
        regression_deltas=[
            RegressionDeltaInput("judge", None, compare_status="config_mismatch"),
            RegressionDeltaInput(
                "small", -0.2, insufficient_n=True, compare_status="insufficient_n"
            ),
            RegressionDeltaInput("latency", -0.5, compare_status="regression", ci_low=-0.6),
        ],
    )
    checks = {c.metric: c for c in result.checks}
    assert checks["regression.judge.non_inferiority"].status == "unavailable"
    assert checks["regression.small.non_inferiority"].status == "unavailable"
    assert "regression.latency.non_inferiority" not in checks  # speed, not answer quality


# ---- CLI output ------------------------------------------------------------------------


def test_power_note_targets_the_margin() -> None:
    policy = {"regression": {"max_delta": -0.10, "non_inferiority_margin": 0.03}}
    assert detectable_delta_target(policy) == 0.03
    notes = power_notes(
        [{"metric": "hit_at_k", "min_detectable_delta": 0.28, "n_paired": 20}], policy
    )
    assert len(notes) == 1
    assert "non_inferiority check may fail even when nothing got worse" in notes[0]


def test_reports_show_ci_and_non_inferiority_threshold() -> None:
    payload = {
        "status": "failed",
        "experiment_id": "e1",
        "baseline_id": "b1",
        "checks": [
            {
                "metric": "regression.hit_at_k.non_inferiority",
                "actual": -0.15,
                "threshold": -0.03,
                "status": "failed",
            }
        ],
        "comparison": [
            {
                "metric": "hit_at_k",
                "candidate": 0.95,
                "baseline": 1.0,
                "delta": -0.05,
                "status": "unchanged",
                "ci_low": -0.15,
                "ci_high": 0.0,
            }
        ],
    }
    md = render_markdown(payload)
    assert "| 95% CI |" in md
    assert "[-0.150, +0.000]" in md
    assert "95% CI lower bound ≥ -0.030" in md
    xml = render_junit(payload)
    assert "actual -0.150, required 95% CI lower bound ≥ -0.030" in xml
