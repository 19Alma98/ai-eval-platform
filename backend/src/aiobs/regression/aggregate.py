from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from aiobs.domain.evaluation import EvaluationResultRecord, EvaluationRun

DELTA_THRESHOLD = 0.01

MetricStatus = Literal["regression", "improved", "unchanged", "unavailable"]
MetricName = Literal["mean_score", "pass_rate"]

_EPOCH = datetime.min.replace(tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class Aggregates:
    n_items: int
    n_scored: int
    n_error: int
    n_skipped: int
    mean_score: float | None
    pass_rate: float | None


@dataclass(frozen=True, slots=True)
class MetricComparison:
    evaluator_id: uuid.UUID
    evaluator_name: str | None
    metric: MetricName
    candidate: float | None
    baseline: float | None
    delta: float | None
    status: MetricStatus


def _run_recency(run: EvaluationRun) -> datetime:
    stamp = run.finished_at or run.started_at
    if stamp is None:
        return _EPOCH
    if stamp.tzinfo is None:
        return stamp.replace(tzinfo=UTC)
    return stamp


def select_latest_runs(runs: Iterable[EvaluationRun]) -> dict[uuid.UUID, EvaluationRun]:
    latest: dict[uuid.UUID, EvaluationRun] = {}
    for run in runs:
        current = latest.get(run.evaluator_id)
        if current is None or _run_recency(run) >= _run_recency(current):
            latest[run.evaluator_id] = run
    return latest


def select_runs(
    runs: Iterable[EvaluationRun],
    *,
    run_ids: list[uuid.UUID] | None = None,
    evaluator_ids: list[uuid.UUID] | None = None,
) -> list[EvaluationRun]:
    run_list = list(runs)
    if run_ids is not None:
        wanted = set(run_ids)
        selected = [run for run in run_list if run.id in wanted]
        found = {run.id for run in selected}
        missing = wanted - found
        if missing:
            raise ValueError(f"Unknown run ids for experiment: {sorted(missing, key=str)}")
    else:
        selected = list(select_latest_runs(run_list).values())

    if evaluator_ids is not None:
        allowed = set(evaluator_ids)
        selected = [run for run in selected if run.evaluator_id in allowed]

    return selected


def _normalize_label(label: str | None) -> str | None:
    if label is None:
        return None
    return label.strip().upper()


def aggregate_results(results: Iterable[EvaluationResultRecord]) -> Aggregates:
    items = list(results)
    scores = [r.score for r in items if r.score is not None]
    labels = [_normalize_label(r.label) for r in items]
    n_error = sum(1 for label in labels if label == "ERROR")
    n_skipped = sum(1 for label in labels if label == "SKIPPED")
    n_pass = sum(1 for label in labels if label == "PASS")
    # Coverage-aware: missing scores (SKIPPED/ERROR) count as 0.0 in the mean.
    covered_scores = [r.score if r.score is not None else 0.0 for r in items]
    mean_score = sum(covered_scores) / len(covered_scores) if covered_scores else None
    pass_rate = (n_pass / len(items)) if items else None
    return Aggregates(
        n_items=len(items),
        n_scored=len(scores),
        n_error=n_error,
        n_skipped=n_skipped,
        mean_score=mean_score,
        pass_rate=pass_rate,
    )


def classify_delta(
    candidate: float | None,
    baseline: float | None,
    *,
    threshold: float = DELTA_THRESHOLD,
) -> tuple[float | None, MetricStatus]:
    if candidate is None or baseline is None:
        return None, "unavailable"
    delta = candidate - baseline
    if abs(delta) < threshold:
        return delta, "unchanged"
    if delta > 0:
        return delta, "improved"
    return delta, "regression"


def compare_evaluator_metrics(
    *,
    evaluator_id: uuid.UUID,
    evaluator_name: str | None,
    candidate: Aggregates,
    baseline: Aggregates,
    threshold: float = DELTA_THRESHOLD,
) -> list[MetricComparison]:
    rows: list[MetricComparison] = []
    for metric, cand_value, base_value in (
        ("mean_score", candidate.mean_score, baseline.mean_score),
        ("pass_rate", candidate.pass_rate, baseline.pass_rate),
    ):
        delta, status = classify_delta(cand_value, base_value, threshold=threshold)
        rows.append(
            MetricComparison(
                evaluator_id=evaluator_id,
                evaluator_name=evaluator_name,
                metric=metric,  # type: ignore[arg-type]
                candidate=cand_value,
                baseline=base_value,
                delta=delta,
                status=status,
            )
        )
    return rows
