from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING

from opengrade.models import (
    EvaluateResponse,
    ExperimentCompareResponse,
    ExperimentResponse,
    ExperimentSummaryResponse,
    MetricComparisonResponse,
)

if TYPE_CHECKING:
    from opengrade.experiment.runtime import ItemRun


@dataclass
class ExperimentResult:
    """Outcome of a finished experiment: server scores, local scores, baseline delta."""

    experiment: ExperimentResponse
    url: str
    items: list[ItemRun]
    evaluation: EvaluateResponse | None = None
    server_summary: ExperimentSummaryResponse | None = None
    comparison: ExperimentCompareResponse | None = None
    baseline_id: str | None = None

    @property
    def id(self) -> str:
        return self.experiment.id

    @property
    def status(self) -> str | None:
        if self.evaluation is not None:
            return self.evaluation.experiment.status
        return self.experiment.status

    @property
    def errors(self) -> list[ItemRun]:
        return [run for run in self.items if run.error is not None]

    @property
    def repeats(self) -> int:
        """Runs per item (``evaluate(repeats=...)``)."""
        return max((run.repeat for run in self.items), default=0) + 1

    @property
    def local_metrics(self) -> dict[str, float | None]:
        """In-process mean per local metric; with repeats each item weighs once."""
        names: list[str] = []
        for run in self.items:
            for name in run.scores:
                if name not in names:
                    names.append(name)
        means: dict[str, float | None] = {}
        for name in names:
            per_item: dict[str, list[float]] = {}
            for run in self.items:
                if (v := run.scores.get(name)) is not None:
                    per_item.setdefault(run.item.id, []).append(v)
            values = [sum(vs) / len(vs) for vs in per_item.values()]
            means[name] = sum(values) / len(values) if values else None
        return means

    @property
    def metrics(self) -> dict[str, float | None]:
        """Mean score per metric as aggregated by the platform.

        Local metrics are submitted too, so they appear here under their name; the
        in-process mean is only a fallback when the submission failed.
        """
        means: dict[str, float | None] = {}
        if self.server_summary is not None:
            for row in self.server_summary.evaluators:
                means[row.evaluator_name or row.evaluator_id or "?"] = row.mean_score
        for name, mean in self.local_metrics.items():
            means.setdefault(name, mean)
        return means

    @property
    def experiment_metrics(self) -> dict[str, float]:
        """Experiment-level scalars: ``log_metrics`` values plus the SDK's ``opengrade.*`` ones."""
        if self.server_summary is None:
            return {}
        return dict(self.server_summary.experiment_metrics)

    def _experiment_metric_lines(self) -> list[str]:
        values = self.experiment_metrics
        if not values:
            return []
        deltas = {
            row.key: row.delta
            for row in (self.comparison.experiment_metrics if self.comparison else [])
        }
        width = max(len(key) for key in values)
        lines = ["  experiment metrics:"]
        for key, value in sorted(values.items()):
            delta = deltas.get(key)
            suffix = f"  {delta:+.3f} vs baseline" if delta is not None else ""
            lines.append(f"    {key.ljust(width)}  {_fmt(value)}{suffix}")
        return lines

    @property
    def groups(self) -> dict[str, dict[str, float | None]]:
        """Mean score per group value and metric (``evaluate(group_by=...)``)."""
        if self.server_summary is None:
            return {}
        return {
            group.value: {
                row.evaluator_name or row.evaluator_id or "?": row.mean_score
                for row in group.evaluators
            }
            for group in self.server_summary.groups
        }

    def _group_lines(self) -> list[str]:
        if self.server_summary is None or not self.server_summary.groups:
            return []
        deltas: dict[tuple[str, str], MetricComparisonResponse] = {}
        for compared in self.comparison.groups if self.comparison else []:
            for metric in compared.metrics:
                if metric.metric == "mean_score":
                    key = (compared.value, metric.evaluator_name or metric.evaluator_id or "")
                    deltas[key] = metric
        rows: list[tuple[str, ...]] = []
        for group in self.server_summary.groups:
            for ev in group.evaluators:
                name = ev.evaluator_name or ev.evaluator_id or "?"
                rows.append(
                    (
                        f"{group.value} (n={group.n_items})",
                        name,
                        _fmt(ev.mean_score),
                        _fmt_delta(deltas.get((group.value, name))),
                    )
                )
        widths = [max(len(r[i]) for r in rows) for i in range(4)]
        lines = [f"  by {self.server_summary.group_by}:"]
        for cells in rows:
            lines.append("    " + "  ".join(c.ljust(w) for c, w in zip(cells, widths, strict=True)))
        return lines

    def _comparison_by_name(self) -> dict[str, MetricComparisonResponse]:
        if self.comparison is None:
            return {}
        rows: dict[str, MetricComparisonResponse] = {}
        for row in self.comparison.metrics:
            key = row.evaluator_name or row.evaluator_id or ""
            rows.setdefault(key, row)
        return rows

    @property
    def flaky(self) -> dict[str, int]:
        """Per metric: items whose verdict changed between repeats (empty without repeats)."""
        if self.server_summary is None or self.repeats < 2:
            return {}
        return {
            row.evaluator_name or row.evaluator_id or "?": row.n_flaky
            for row in self.server_summary.evaluators
        }

    def summary(self) -> str:
        """Plain-text table: one row per metric with the baseline delta, then experiment metrics."""
        n = len({run.item.id for run in self.items})
        repeats = self.repeats
        runs = f" x {repeats} repeats" if repeats > 1 else ""
        head = (
            f"Experiment {self.experiment.name} ({self.id}): "
            f"{n} item{'s' if n != 1 else ''}{runs}, {len(self.errors)} errors, "
            f"status={self.status}"
        )
        compared = self._comparison_by_name()
        flaky = self.flaky
        rows: list[tuple[str, ...]] = []
        seen: set[str] = set()
        if self.server_summary is not None:
            for ev in self.server_summary.evaluators:
                name = ev.evaluator_name or ev.evaluator_id or "?"
                seen.add(name)
                # Nothing scored (every item errored or was skipped): the server's 0.0
                # is not a score, show it as missing.
                unscored = ev.n_scored == 0
                row: tuple[str, ...] = (
                    name,
                    "-" if unscored else _fmt(ev.mean_score),
                    "-" if unscored else _fmt(ev.pass_rate),
                )
                if flaky:
                    row += (str(flaky.get(name, 0)),)
                rows.append((*row, _fmt_delta(compared.get(name))))
        for name, mean in self.local_metrics.items():
            if name not in seen:  # submission failed: show the in-process mean
                local_row: tuple[str, ...] = (f"{name} (local only)", _fmt(mean), "-")
                rows.append((*local_row, *(("-",) if flaky else ()), ""))
        lines = [head]
        if rows:
            header: tuple[str, ...] = ("metric", "mean", "pass_rate")
            if flaky:
                header += ("flaky",)
            header += ("vs baseline" if compared else "",)
            widths = [max(len(r[i]) for r in [header, *rows]) for i in range(len(header))]
            for row in [header, *rows]:
                lines.append("  " + "  ".join(c.ljust(w) for c, w in zip(row, widths, strict=True)))
        else:
            lines.append("  (no metrics scored)")
        lines.extend(self._skipped_lines())
        lines.extend(self._error_lines())
        lines.extend(self._group_lines())
        lines.extend(self._experiment_metric_lines())
        lines.append(f"  view: {self.url}")
        for run in self.errors[:_MAX_ERROR_LINKS]:
            lines.append(f"  error: {run.trace_url or run.url or run.item.id}")
        return "\n".join(line.rstrip() for line in lines)

    def _skipped_lines(self) -> list[str]:
        """Explain metrics that did not apply to some items (a ``-`` mean is otherwise opaque)."""
        if self.server_summary is None:
            return []
        lines: list[str] = []
        for ev in self.server_summary.evaluators:
            skipped = ev.n_skipped or 0
            if not skipped:
                continue
            name = ev.evaluator_name or ev.evaluator_id or "?"
            total = ev.n_items if ev.n_items is not None else skipped
            hint = _SKIP_HINTS.get(name, "the test case lacks the data this metric needs")
            lines.append(f"  note: {name} skipped on {skipped}/{total} items: {hint}")
        return lines

    def _error_lines(self) -> list[str]:
        """Say when a metric could not run: a failed judge must not read as a score of 0."""
        if self.server_summary is None:
            return []
        lines: list[str] = []
        for ev in self.server_summary.evaluators:
            errors = ev.n_error or 0
            if not errors:
                continue
            name = ev.evaluator_name or ev.evaluator_id or "?"
            total = ev.n_items if ev.n_items is not None else errors
            lines.append(
                f"  note: {name} could not run on {errors}/{total} items (ERROR, not a score): "
                "open the experiment for the reason; LLM judges need a judge model on the server"
            )
        return lines

    def __str__(self) -> str:
        return self.summary()


_MAX_ERROR_LINKS = 5
_SKIP_HINTS: dict[str, str] = {
    "must_contain": 'add `"must_contain": ["phrase", ...]` to the test case',
    "exact_match": "add `expected_output` to the test case",
    "contains": "add `expected_output` to the test case",
    "hit_at_k": "add `expected_doc_ids` to the test case",
    "recall_at_k": "add `expected_doc_ids` to the test case",
    "mrr": "add `expected_doc_ids` to the test case",
}


def announce(result: ExperimentResult) -> None:
    """Print where to see the results; ``OPENGRADE_QUIET=1`` silences it.

    Links use ``OPENGRADE_UI_URL`` when set, otherwise the API host (see ``ui_base_url``).
    """
    if os.getenv("OPENGRADE_QUIET", "").strip().lower() in {"1", "true", "yes"}:
        return
    print(f"opengrade: experiment {result.experiment.name} -> {result.url}", file=sys.stderr)


def _fmt(value: float | None) -> str:
    return "-" if value is None else f"{value:.3f}"


_STATUS_LABELS = {
    "unchanged": "not significant",
    "insufficient_n": "insufficient n",
}


def _fmt_delta(row: MetricComparisonResponse | None) -> str:
    if row is None or row.delta is None:
        return ""
    status = row.status or ""
    label = _STATUS_LABELS.get(status, status.replace("_", " ") if status else "")
    return f"{row.delta:+.3f} {label}".rstrip()
