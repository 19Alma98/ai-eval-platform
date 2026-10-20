from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence, Set
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from opengrade_server.domain.evaluation import EvaluationResultRecord, EvaluationRun
from opengrade_server.regression.bootstrap import comparison_seed, paired_mean_ci

DELTA_THRESHOLD = 0.01
MIN_APPLICABLE_ITEMS = 5

MetricStatus = Literal[
    "regression", "improved", "unchanged", "unavailable", "config_mismatch", "insufficient_n"
]
MetricName = Literal["mean_score", "pass_rate"]

_EPOCH = datetime.min.replace(tzinfo=UTC)
_TERMINAL_RUN_STATUSES = frozenset({"PASSED", "FAILED", "ERROR", "SKIPPED"})


@dataclass(frozen=True, slots=True)
class Aggregates:
    n_items: int
    n_scored: int
    n_error: int
    n_skipped: int
    n_applicable: int
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
    ci_low: float | None = None
    ci_high: float | None = None
    n_paired: int | None = None


def _run_recency(run: EvaluationRun) -> datetime:
    stamp = run.finished_at or run.started_at
    if stamp is None:
        return _EPOCH
    if stamp.tzinfo is None:
        return stamp.replace(tzinfo=UTC)
    return stamp


def select_latest_runs(
    runs: Iterable[EvaluationRun],
    *,
    run_ids_with_results: Set[uuid.UUID],
) -> dict[uuid.UUID, EvaluationRun]:
    """Latest terminal run per evaluator that has at least one result row.

    PENDING/RUNNING and empty interrupted ERROR runs are skipped so they do not
    hide a previous scored run in summaries and quality gates.
    """
    latest: dict[uuid.UUID, EvaluationRun] = {}
    for run in runs:
        if run.status not in _TERMINAL_RUN_STATUSES:
            continue
        if run.id not in run_ids_with_results:
            continue
        current = latest.get(run.evaluator_id)
        if current is None or _run_recency(run) >= _run_recency(current):
            latest[run.evaluator_id] = run
    return latest


INPUTS_FINGERPRINT_KEY = "inputs_fingerprint"


def run_is_stale(run: EvaluationRun, current_fingerprint: str) -> bool:
    scored = run.metadata.get(INPUTS_FINGERPRINT_KEY)
    return scored is not None and scored != current_fingerprint


def select_runs(
    runs: Iterable[EvaluationRun],
    *,
    run_ids: list[uuid.UUID] | None = None,
    evaluator_ids: list[uuid.UUID] | None = None,
    current_fingerprint: str | None = None,
    run_ids_with_results: Set[uuid.UUID] | None = None,
) -> list[EvaluationRun]:
    """Pick runs to report on: explicit ``run_ids``, else the latest fresh run per evaluator.

    With ``current_fingerprint``, runs scored on different inputs (outputs or test set
    changed since) are stale and skipped. Runs without a fingerprint predate it and
    are kept.

    Auto-selection (no ``run_ids``) requires ``run_ids_with_results`` and keeps only
    the latest terminal run that has results. Explicit ``run_ids`` are returned as-is.
    """
    run_list = list(runs)
    if run_ids is None and current_fingerprint is not None:
        run_list = [run for run in run_list if not run_is_stale(run, current_fingerprint)]
    if run_ids is not None:
        wanted = set(run_ids)
        selected = [run for run in run_list if run.id in wanted]
        found = {run.id for run in selected}
        missing = wanted - found
        if missing:
            raise ValueError(f"Unknown run ids for experiment: {sorted(missing, key=str)}")
    else:
        if run_ids_with_results is None:
            raise ValueError("run_ids_with_results is required when run_ids is omitted")
        selected = list(
            select_latest_runs(run_list, run_ids_with_results=run_ids_with_results).values()
        )

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
    # SKIPPED means the metric does not apply to the item (e.g. no must_contain gold),
    # so it is excluded from the denominator. ERROR still counts as 0.0 so evaluator
    # or infra failures cannot inflate the mean.
    applicable = [r for r, label in zip(items, labels, strict=True) if label != "SKIPPED"]
    covered_scores = [r.score if r.score is not None else 0.0 for r in applicable]
    mean_score = sum(covered_scores) / len(covered_scores) if covered_scores else None
    pass_rate = (n_pass / len(applicable)) if applicable else None
    return Aggregates(
        n_items=len(items),
        n_scored=len(scores),
        n_error=n_error,
        n_skipped=n_skipped,
        n_applicable=len(applicable),
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


def runs_config_mismatch(candidate: EvaluationRun | None, baseline: EvaluationRun | None) -> bool:
    """True when candidate and baseline were not scored the same way.

    Differs when both recorded a config_hash and it differs (e.g. k=3 vs k=5), or when
    the judge prompt version or judge model differs. A missing prompt_version counts as its own
    version: judge runs from before v3 carry none and are not comparable with v3.
    Runs without a config_hash (legacy) are otherwise assumed comparable.
    """
    if candidate is None or baseline is None:
        return False
    if candidate.metadata.get("prompt_version") != baseline.metadata.get("prompt_version"):
        return True
    cand_model = candidate.metadata.get("judge_model")
    base_model = baseline.metadata.get("judge_model")
    if cand_model is not None and base_model is not None and cand_model != base_model:
        return True
    cand_hash = candidate.metadata.get("config_hash")
    base_hash = baseline.metadata.get("config_hash")
    return cand_hash is not None and base_hash is not None and cand_hash != base_hash


def _metric_value(result: EvaluationResultRecord, metric: MetricName) -> float:
    if metric == "pass_rate":
        return 1.0 if _normalize_label(result.label) == "PASS" else 0.0
    return result.score if result.score is not None else 0.0


def paired_item_diffs(
    candidate_results: Iterable[EvaluationResultRecord],
    baseline_results: Iterable[EvaluationResultRecord],
    *,
    metric: MetricName,
) -> list[float]:
    """Paired cand−base values for applicable items present on both sides."""
    cand = {
        r.dataset_item_id: r for r in candidate_results if _normalize_label(r.label) != "SKIPPED"
    }
    base = {
        r.dataset_item_id: r for r in baseline_results if _normalize_label(r.label) != "SKIPPED"
    }
    shared = sorted(set(cand) & set(base), key=str)
    return [_metric_value(cand[i], metric) - _metric_value(base[i], metric) for i in shared]


def _status_from_ci(ci_low: float, ci_high: float) -> MetricStatus:
    if ci_low > 0:
        return "improved"
    if ci_high < 0:
        return "regression"
    return "unchanged"


def compare_evaluator_metrics(
    *,
    evaluator_id: uuid.UUID,
    evaluator_name: str | None,
    candidate: Aggregates,
    baseline: Aggregates,
    candidate_results: Sequence[EvaluationResultRecord] | None = None,
    baseline_results: Sequence[EvaluationResultRecord] | None = None,
    candidate_run_id: uuid.UUID | None = None,
    baseline_run_id: uuid.UUID | None = None,
    seed: int | None = None,
    threshold: float = DELTA_THRESHOLD,
    config_mismatch: bool = False,
) -> list[MetricComparison]:
    rows: list[MetricComparison] = []
    for metric, cand_value, base_value in (
        ("mean_score", candidate.mean_score, baseline.mean_score),
        ("pass_rate", candidate.pass_rate, baseline.pass_rate),
    ):
        metric_name: MetricName = metric  # type: ignore[assignment]
        delta: float | None
        status: MetricStatus
        ci_low: float | None = None
        ci_high: float | None = None
        n_paired: int | None = None
        if config_mismatch:
            # Scores measured under different configs: a delta would be meaningless.
            delta, status = None, "config_mismatch"
        else:
            delta, status = classify_delta(cand_value, base_value, threshold=threshold)
            if status in ("regression", "improved", "unchanged"):
                if candidate_results is not None and baseline_results is not None:
                    diffs = paired_item_diffs(
                        candidate_results,
                        baseline_results,
                        metric=metric_name,
                    )
                    n_paired = len(diffs)
                    if n_paired < MIN_APPLICABLE_ITEMS:
                        status = "insufficient_n"
                    elif status != "unchanged":
                        # Non-trivial aggregate delta: require CI to exclude 0.
                        metric_seed = (
                            seed
                            if seed is not None
                            else comparison_seed(
                                evaluator_id,
                                candidate_run_id or uuid.UUID(int=0),
                                baseline_run_id or uuid.UUID(int=0),
                                metric_name,
                            )
                        )
                        ci_low, ci_high = paired_mean_ci(diffs, seed=metric_seed)
                        status = _status_from_ci(ci_low, ci_high)
                elif min(candidate.n_applicable, baseline.n_applicable) < MIN_APPLICABLE_ITEMS:
                    status = "insufficient_n"
        rows.append(
            MetricComparison(
                evaluator_id=evaluator_id,
                evaluator_name=evaluator_name,
                metric=metric_name,
                candidate=cand_value,
                baseline=base_value,
                delta=delta,
                status=status,
                ci_low=ci_low,
                ci_high=ci_high,
                n_paired=n_paired,
            )
        )
    return rows
