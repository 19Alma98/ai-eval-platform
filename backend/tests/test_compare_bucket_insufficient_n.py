from __future__ import annotations

import uuid

from aiobs.application.compare import ExperimentComparison
from aiobs.regression.aggregate import Aggregates, compare_evaluator_metrics


def test_experiment_comparison_buckets_insufficient_n() -> None:
    metrics = compare_evaluator_metrics(
        evaluator_id=uuid.uuid4(),
        evaluator_name="quality",
        candidate=Aggregates(3, 3, 0, 0, 3, 0.5, 0.5),
        baseline=Aggregates(3, 3, 0, 0, 3, 0.9, 0.9),
    )
    comparison = ExperimentComparison(
        experiment_id=uuid.uuid4(),
        baseline_experiment_id=uuid.uuid4(),
        metrics=metrics,
        regressions=[m for m in metrics if m.status == "regression"],
        improved=[m for m in metrics if m.status == "improved"],
        unchanged=[m for m in metrics if m.status == "unchanged"],
        config_mismatches=[m for m in metrics if m.status == "config_mismatch"],
        insufficient_n=[m for m in metrics if m.status == "insufficient_n"],
    )
    assert comparison.regressions == []
    assert len(comparison.insufficient_n) == 2
