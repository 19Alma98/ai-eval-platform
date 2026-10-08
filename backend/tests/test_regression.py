from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from aiobs.domain.evaluation import EvaluationResultRecord, EvaluationRun
from aiobs.regression.aggregate import (
    DELTA_THRESHOLD,
    Aggregates,
    aggregate_results,
    classify_delta,
    compare_evaluator_metrics,
    runs_config_mismatch,
    select_latest_runs,
    select_runs,
)


def _run(
    *,
    evaluator_id: uuid.UUID | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    run_id: uuid.UUID | None = None,
) -> EvaluationRun:
    return EvaluationRun(
        id=run_id or uuid.uuid4(),
        experiment_id=uuid.uuid4(),
        evaluator_id=evaluator_id or uuid.uuid4(),
        status="PASSED",
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
    selected = select_latest_runs([older, newer])
    assert selected[evaluator_id].id == newer.id


def test_select_runs_explicit_ids_and_evaluator_filter() -> None:
    e1 = uuid.uuid4()
    e2 = uuid.uuid4()
    r1 = _run(evaluator_id=e1)
    r2 = _run(evaluator_id=e2)
    selected = select_runs([r1, r2], run_ids=[r1.id], evaluator_ids=[e1])
    assert [r.id for r in selected] == [r1.id]


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


def test_compare_evaluator_metrics_emits_both_metrics() -> None:
    evaluator_id = uuid.uuid4()
    candidate = Aggregates(10, 10, 0, 0, 0.7, 0.7)
    baseline = Aggregates(10, 10, 0, 0, 0.9, 0.9)
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
        candidate=Aggregates(10, 10, 0, 0, 0.7, 0.7),
        baseline=Aggregates(10, 10, 0, 0, 0.9, 0.9),
        config_mismatch=True,
    )
    assert all(r.status == "config_mismatch" for r in rows)
    assert all(r.delta is None for r in rows)
    # Raw values stay visible so the user can see what was measured.
    assert rows[0].candidate == 0.7 and rows[0].baseline == 0.9
