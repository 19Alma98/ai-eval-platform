from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from opengrade_server.domain.evaluation import EvaluationResultRecord, EvaluationRun
from opengrade_server.regression.aggregate import (
    DELTA_THRESHOLD,
    MIN_APPLICABLE_ITEMS,
    Aggregates,
    aggregate_results,
    classify_delta,
    compare_evaluator_metrics,
    paired_item_diffs,
    runs_config_mismatch,
    select_latest_runs,
    select_runs,
)
from opengrade_server.regression.bootstrap import comparison_seed, paired_mean_ci


def _run(
    *,
    evaluator_id: uuid.UUID | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    run_id: uuid.UUID | None = None,
    status: str = "PASSED",
) -> EvaluationRun:
    return EvaluationRun(
        id=run_id or uuid.uuid4(),
        experiment_id=uuid.uuid4(),
        evaluator_id=evaluator_id or uuid.uuid4(),
        status=status,
        started_at=started_at,
        finished_at=finished_at,
        metadata={},
    )


def _result(
    *,
    score: float | None = None,
    label: str | None = None,
) -> EvaluationResultRecord:
    return EvaluationResultRecord.create(
        uuid.uuid4(),
        uuid.uuid4(),
        score=score,
        label=label,
    )


def test_select_latest_runs_prefers_newest_finished_at() -> None:
    evaluator_id = uuid.uuid4()
    older = _run(
        evaluator_id=evaluator_id,
        finished_at=datetime(2024, 1, 1, tzinfo=UTC),
    )
    newer = _run(
        evaluator_id=evaluator_id,
        finished_at=datetime(2024, 1, 2, tzinfo=UTC),
    )
    selected = select_latest_runs(
        [older, newer],
        run_ids_with_results={older.id, newer.id},
    )
    assert selected[evaluator_id].id == newer.id


def test_select_latest_runs_skips_non_terminal_even_if_newer() -> None:
    evaluator_id = uuid.uuid4()
    older = _run(
        evaluator_id=evaluator_id,
        finished_at=datetime(2024, 1, 1, tzinfo=UTC),
        status="PASSED",
    )
    pending = _run(
        evaluator_id=evaluator_id,
        started_at=datetime(2024, 1, 2, tzinfo=UTC),
        status="PENDING",
    )
    running = _run(
        evaluator_id=evaluator_id,
        started_at=datetime(2024, 1, 3, tzinfo=UTC),
        status="RUNNING",
    )
    selected = select_latest_runs(
        [older, pending, running],
        run_ids_with_results={older.id, pending.id, running.id},
    )
    assert selected[evaluator_id].id == older.id


def test_select_latest_runs_skips_terminal_without_results() -> None:
    evaluator_id = uuid.uuid4()
    scored = _run(
        evaluator_id=evaluator_id,
        finished_at=datetime(2024, 1, 1, tzinfo=UTC),
        status="PASSED",
    )
    empty_error = _run(
        evaluator_id=evaluator_id,
        finished_at=datetime(2024, 1, 2, tzinfo=UTC),
        status="ERROR",
    )
    selected = select_latest_runs(
        [scored, empty_error],
        run_ids_with_results={scored.id},
    )
    assert selected[evaluator_id].id == scored.id


def test_select_latest_runs_prefers_newer_terminal_with_results() -> None:
    evaluator_id = uuid.uuid4()
    older = _run(
        evaluator_id=evaluator_id,
        finished_at=datetime(2024, 1, 1, tzinfo=UTC),
        status="PASSED",
    )
    newer_error = _run(
        evaluator_id=evaluator_id,
        finished_at=datetime(2024, 1, 2, tzinfo=UTC),
        status="ERROR",
    )
    selected = select_latest_runs(
        [older, newer_error],
        run_ids_with_results={older.id, newer_error.id},
    )
    assert selected[evaluator_id].id == newer_error.id


def test_select_runs_explicit_ids_and_evaluator_filter() -> None:
    e1 = uuid.uuid4()
    e2 = uuid.uuid4()
    r1 = _run(evaluator_id=e1)
    r2 = _run(evaluator_id=e2)
    selected = select_runs([r1, r2], run_ids=[r1.id], evaluator_ids=[e1])
    assert [r.id for r in selected] == [r1.id]


def test_select_runs_explicit_ids_ignore_results_filter() -> None:
    empty = _run(status="ERROR")
    selected = select_runs([empty], run_ids=[empty.id], run_ids_with_results=set())
    assert [r.id for r in selected] == [empty.id]


def test_select_runs_unknown_id_raises() -> None:
    missing = uuid.uuid4()
    with pytest.raises(ValueError, match=str(missing)):
        select_runs([_run()], run_ids=[missing])


def test_aggregate_excludes_skipped_and_counts_error_as_zero() -> None:
    aggregates = aggregate_results(
        [
            _result(score=1.0, label="PASS"),
            _result(score=0.0, label="FAIL"),
            _result(score=None, label="SKIPPED"),
            _result(score=None, label="ERROR"),
        ]
    )
    assert aggregates.n_items == 4
    assert aggregates.n_scored == 2
    assert aggregates.n_skipped == 1
    assert aggregates.n_error == 1
    assert aggregates.mean_score == pytest.approx(1 / 3)
    assert aggregates.pass_rate == pytest.approx(1 / 3)


def test_aggregate_skipped_does_not_lower_mean() -> None:
    aggregates = aggregate_results(
        [
            _result(score=1.0, label="PASS"),
            _result(score=None, label="SKIPPED"),
            _result(score=None, label="skipped"),
        ]
    )
    assert aggregates.mean_score == 1.0
    assert aggregates.pass_rate == 1.0


def test_aggregate_all_skipped_is_null() -> None:
    aggregates = aggregate_results(
        [
            _result(score=None, label="SKIPPED"),
            _result(score=None, label="SKIPPED"),
        ]
    )
    assert aggregates.n_skipped == 2
    assert aggregates.mean_score is None
    assert aggregates.pass_rate is None


def test_aggregate_pass_rate_normalizes_label_casing() -> None:
    aggregates = aggregate_results(
        [
            _result(score=1.0, label="pass"),
            _result(score=0.0, label="Fail"),
        ]
    )
    assert aggregates.pass_rate == 0.5
    assert aggregates.mean_score == 0.5


def test_aggregate_skipped_plus_error_counts_error_as_zero() -> None:
    aggregates = aggregate_results(
        [
            _result(score=None, label="SKIPPED"),
            _result(score=None, label="ERROR"),
        ]
    )
    assert aggregates.mean_score == 0.0
    assert aggregates.pass_rate == 0.0


def test_aggregate_empty_is_null() -> None:
    aggregates = aggregate_results([])
    assert aggregates.mean_score is None
    assert aggregates.pass_rate is None


def test_classify_delta_threshold_and_directions() -> None:
    delta, status = classify_delta(0.805, 0.800)
    assert status == "unchanged"
    assert delta is not None and abs(delta - 0.005) < 1e-12
    assert classify_delta(0.90, 0.80)[1] == "improved"
    assert classify_delta(0.70, 0.80)[1] == "regression"
    assert classify_delta(None, 0.5) == (None, "unavailable")
    assert classify_delta(0.5, None) == (None, "unavailable")


def test_aggregate_exposes_n_applicable() -> None:
    aggregates = aggregate_results(
        [
            _result(score=1.0, label="PASS"),
            _result(score=0.0, label="FAIL"),
            _result(score=None, label="SKIPPED"),
            _result(score=None, label="ERROR"),
        ]
    )
    assert aggregates.n_applicable == 3  # PASS + FAIL + ERROR; not SKIPPED


def test_compare_insufficient_n_when_either_side_below_min() -> None:
    evaluator_id = uuid.uuid4()
    candidate = Aggregates(4, 4, 0, 0, 4, 0.5, 0.5)
    baseline = Aggregates(10, 10, 0, 0, 10, 0.9, 0.9)
    assert MIN_APPLICABLE_ITEMS == 5
    rows = compare_evaluator_metrics(
        evaluator_id=evaluator_id,
        evaluator_name="quality",
        candidate=candidate,
        baseline=baseline,
    )
    assert all(r.status == "insufficient_n" for r in rows)
    assert all(r.delta == pytest.approx(-0.4) for r in rows)


def test_compare_regression_when_both_sides_meet_min_n() -> None:
    # Without item results, legacy path still classifies by |delta| once n >= 5.
    rows = compare_evaluator_metrics(
        evaluator_id=uuid.uuid4(),
        evaluator_name="quality",
        candidate=Aggregates(5, 5, 0, 0, 5, 0.5, 0.5),
        baseline=Aggregates(5, 5, 0, 0, 5, 0.9, 0.9),
    )
    assert all(r.status == "regression" for r in rows)


def _binary_pair(
    *,
    n: int,
    candidate_fails: set[int],
    baseline_fails: set[int] | None = None,
) -> tuple[list[EvaluationResultRecord], list[EvaluationResultRecord], Aggregates, Aggregates]:
    baseline_fails = baseline_fails or set()
    item_ids = [uuid.uuid4() for _ in range(n)]
    cand_run = uuid.uuid4()
    base_run = uuid.uuid4()
    candidate: list[EvaluationResultRecord] = []
    baseline: list[EvaluationResultRecord] = []
    for i, item_id in enumerate(item_ids):
        cand_pass = i not in candidate_fails
        base_pass = i not in baseline_fails
        candidate.append(
            EvaluationResultRecord.create(
                cand_run,
                item_id,
                score=1.0 if cand_pass else 0.0,
                label="PASS" if cand_pass else "FAIL",
            )
        )
        baseline.append(
            EvaluationResultRecord.create(
                base_run,
                item_id,
                score=1.0 if base_pass else 0.0,
                label="PASS" if base_pass else "FAIL",
            )
        )
    return candidate, baseline, aggregate_results(candidate), aggregate_results(baseline)


def test_compare_one_flip_on_eight_items_is_unchanged_not_regression() -> None:
    candidate, baseline, cand_agg, base_agg = _binary_pair(n=8, candidate_fails={0})
    rows = compare_evaluator_metrics(
        evaluator_id=uuid.uuid4(),
        evaluator_name="quality",
        candidate=cand_agg,
        baseline=base_agg,
        candidate_results=candidate,
        baseline_results=baseline,
        seed=42,
    )
    mean_row = next(r for r in rows if r.metric == "mean_score")
    assert mean_row.delta == pytest.approx(-0.125)
    assert mean_row.status == "unchanged"
    assert mean_row.n_paired == 8
    assert mean_row.ci_low is not None and mean_row.ci_high is not None
    assert mean_row.ci_low <= 0 <= mean_row.ci_high


def test_compare_large_consistent_drop_is_regression() -> None:
    # Baseline all PASS; candidate fails half of 30 items → clear regression.
    candidate, baseline, cand_agg, base_agg = _binary_pair(
        n=30,
        candidate_fails=set(range(15)),
    )
    rows = compare_evaluator_metrics(
        evaluator_id=uuid.uuid4(),
        evaluator_name="quality",
        candidate=cand_agg,
        baseline=base_agg,
        candidate_results=candidate,
        baseline_results=baseline,
        seed=7,
    )
    mean_row = next(r for r in rows if r.metric == "mean_score")
    assert mean_row.delta == pytest.approx(-0.5)
    assert mean_row.status == "regression"
    assert mean_row.ci_high is not None and mean_row.ci_high < 0


def test_compare_paired_insufficient_n_keeps_delta() -> None:
    candidate, baseline, cand_agg, base_agg = _binary_pair(n=4, candidate_fails={0})
    rows = compare_evaluator_metrics(
        evaluator_id=uuid.uuid4(),
        evaluator_name="quality",
        candidate=cand_agg,
        baseline=base_agg,
        candidate_results=candidate,
        baseline_results=baseline,
        seed=1,
    )
    assert all(r.status == "insufficient_n" for r in rows)
    assert all(r.delta == pytest.approx(-0.25) for r in rows)
    assert all(r.n_paired == 4 for r in rows)
    assert all(r.ci_low is None and r.ci_high is None for r in rows)


def test_paired_mean_ci_seed_stability() -> None:
    diffs = [-0.9, -0.4, -0.2, 0.0, 0.1, 0.3, 0.5, 0.8]
    a = paired_mean_ci(diffs, seed=123)
    b = paired_mean_ci(diffs, seed=123)
    c = paired_mean_ci(diffs, seed=456)
    assert a == b
    assert a != c


def test_comparison_seed_includes_metric() -> None:
    eid = uuid.uuid4()
    c = uuid.uuid4()
    b = uuid.uuid4()
    assert comparison_seed(eid, c, b, "mean_score") != comparison_seed(eid, c, b, "pass_rate")


def test_paired_item_diffs_skips_skipped_and_unmatched() -> None:
    shared = uuid.uuid4()
    only_cand = uuid.uuid4()
    run = uuid.uuid4()
    candidate = [
        EvaluationResultRecord.create(run, shared, score=1.0, label="PASS"),
        EvaluationResultRecord.create(run, only_cand, score=0.0, label="FAIL"),
        EvaluationResultRecord.create(run, uuid.uuid4(), score=None, label="SKIPPED"),
    ]
    baseline = [
        EvaluationResultRecord.create(run, shared, score=0.0, label="FAIL"),
    ]
    diffs = paired_item_diffs(candidate, baseline, metric="mean_score")
    assert diffs == [1.0]


def test_compare_config_mismatch_beats_insufficient_n() -> None:
    rows = compare_evaluator_metrics(
        evaluator_id=uuid.uuid4(),
        evaluator_name="quality",
        candidate=Aggregates(2, 2, 0, 0, 2, 0.5, 0.5),
        baseline=Aggregates(2, 2, 0, 0, 2, 0.9, 0.9),
        config_mismatch=True,
    )
    assert all(r.status == "config_mismatch" for r in rows)
    assert all(r.delta is None for r in rows)


def test_compare_evaluator_metrics_emits_both_metrics() -> None:
    evaluator_id = uuid.uuid4()
    candidate = Aggregates(10, 10, 0, 0, 10, 0.7, 0.7)
    baseline = Aggregates(10, 10, 0, 0, 10, 0.9, 0.9)
    rows = compare_evaluator_metrics(
        evaluator_id=evaluator_id,
        evaluator_name="exact",
        candidate=candidate,
        baseline=baseline,
        threshold=DELTA_THRESHOLD,
    )
    assert [r.metric for r in rows] == ["mean_score", "pass_rate"]
    assert all(r.status == "regression" for r in rows)


def _run_with_hash(config_hash: str | None) -> EvaluationRun:
    run = _run()
    if config_hash is None:
        return run
    return EvaluationRun(
        id=run.id,
        experiment_id=run.experiment_id,
        evaluator_id=run.evaluator_id,
        status=run.status,
        started_at=run.started_at,
        finished_at=run.finished_at,
        metadata={"config_hash": config_hash},
    )


def test_runs_config_mismatch_only_when_both_hashes_differ() -> None:
    assert runs_config_mismatch(_run_with_hash("aaa"), _run_with_hash("bbb"))
    assert not runs_config_mismatch(_run_with_hash("aaa"), _run_with_hash("aaa"))
    # Legacy runs without a hash stay comparable.
    assert not runs_config_mismatch(_run_with_hash("aaa"), _run_with_hash(None))
    assert not runs_config_mismatch(None, _run_with_hash("aaa"))


def test_compare_evaluator_metrics_config_mismatch_has_no_delta() -> None:
    rows = compare_evaluator_metrics(
        evaluator_id=uuid.uuid4(),
        evaluator_name="hit_at_k",
        candidate=Aggregates(10, 10, 0, 0, 10, 0.7, 0.7),
        baseline=Aggregates(10, 10, 0, 0, 10, 0.9, 0.9),
        config_mismatch=True,
    )
    assert all(r.status == "config_mismatch" for r in rows)
    assert all(r.delta is None for r in rows)
    # Raw values stay visible so the user can see what was measured.
    assert rows[0].candidate == 0.7 and rows[0].baseline == 0.9


def _run_with_meta(**metadata: object) -> EvaluationRun:
    run = _run_with_hash("aaa")
    return replace(run, metadata={**run.metadata, **metadata})


def test_runs_config_mismatch_on_prompt_version() -> None:
    v3 = _run_with_meta(prompt_version="groundedness.claims.v3")
    rubric = _run_with_meta(prompt_version="groundedness.rubric.v3")
    legacy = _run_with_meta()  # judge run scored before prompt versions were recorded
    assert runs_config_mismatch(v3, rubric)
    assert runs_config_mismatch(v3, legacy)
    assert not runs_config_mismatch(v3, _run_with_meta(prompt_version="groundedness.claims.v3"))
    assert not runs_config_mismatch(legacy, _run_with_meta())


def test_runs_config_mismatch_on_judge_model() -> None:
    pv = "correctness.claims.v3"
    gemma = _run_with_meta(prompt_version=pv, judge_model="ollama/gemma4:e2b")
    claude = _run_with_meta(prompt_version=pv, judge_model="anthropic/claude-sonnet-5-5")
    legacy = _run_with_meta(prompt_version=pv)  # scored before judge_model was recorded
    assert runs_config_mismatch(gemma, claude)
    assert not runs_config_mismatch(
        gemma, _run_with_meta(prompt_version=pv, judge_model="ollama/gemma4:e2b")
    )
    assert not runs_config_mismatch(gemma, legacy)


def test_select_runs_skips_runs_scored_on_other_inputs() -> None:
    evaluator = uuid.uuid4()
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    stale = replace(
        _run(evaluator_id=evaluator, finished_at=t0.replace(hour=2)),
        metadata={"inputs_fingerprint": "old"},
    )
    fresh = replace(
        _run(evaluator_id=evaluator, finished_at=t0.replace(hour=1)),
        metadata={"inputs_fingerprint": "new"},
    )
    legacy = _run(finished_at=t0)
    with_results = {stale.id, fresh.id, legacy.id}
    selected = select_runs(
        [stale, fresh, legacy],
        current_fingerprint="new",
        run_ids_with_results=with_results,
    )
    assert {r.id for r in selected} == {fresh.id, legacy.id}
    # Without a current fingerprint the newest run wins, as before.
    assert stale in select_runs(
        [stale, fresh],
        run_ids_with_results={stale.id, fresh.id},
    )
    # Explicit run ids are honored even when stale.
    assert select_runs([stale, fresh], run_ids=[stale.id], current_fingerprint="new") == [stale]
