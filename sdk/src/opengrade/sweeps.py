"""Parameter sweeps: run the same test set over many configurations and rank them."""

from __future__ import annotations

import inspect
import itertools
import logging
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from opengrade._links import experiments_compare_url, ui_base_url
from opengrade.client import Client
from opengrade.experiment import (
    MAX_REPEATS,
    DatasetLike,
    ExperimentResult,
    Metric,
    _resolve_dataset,
    _resolve_project,
    evaluate,
)
from opengrade.models import DatasetItemResponse, ExperimentResponse
from opengrade.retrieval import evaluate_retrieval

logger = logging.getLogger("opengrade")

SWEEP_PARAM = "sweep"
"""Param holding the sweep name on every experiment of a sweep (filter on it in the UI)."""

MAX_VARIANTS = 200

# Experiment metrics the SDK logs on every run; shown next to quality in the summary.
_RUN_METRICS = ("opengrade.latency_p95_ms", "opengrade.error_rate")


def is_lower_better(metric: str) -> bool:
    """Latency, cost, error and token metrics are lower-is-better; scores higher-is-better."""
    key = metric.lower().removeprefix("opengrade.")
    return key.startswith(("latency", "cost", "error", "tokens")) or key.endswith(
        ("_ms", "_usd", "_tokens", "error_rate")
    )


def expand_grid(grid: Mapping[str, Sequence[Any]]) -> list[dict[str, Any]]:
    """Cartesian product of ``grid`` values, in key order: ``{"a": [1, 2], "b": ["x"]}``
    → ``[{"a": 1, "b": "x"}, {"a": 2, "b": "x"}]``."""
    keys = list(grid)
    values: list[list[Any]] = []
    for key in keys:
        raw = grid[key]
        if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence):
            raise TypeError(f"grid[{key!r}] must be a list of values, got {raw!r}")
        if not raw:
            raise ValueError(f"grid[{key!r}] is empty")
        values.append(list(raw))
    return [dict(zip(keys, combo, strict=True)) for combo in itertools.product(*values)]


def variant_label(params: Mapping[str, Any]) -> str:
    """``{"model": "gemma", "k": 5}`` → ``"model=gemma, k=5"``."""
    return ", ".join(f"{key}={_short(value)}" for key, value in params.items()) or "default"


def _short(value: Any) -> str:
    text = value if isinstance(value, str) else repr(value)
    return text if len(text) <= 40 else text[:39] + "…"


@dataclass
class SweepRun:
    """One configuration of a sweep: its params and the experiment it produced."""

    params: dict[str, Any]
    result: ExperimentResult | None = None
    error: str | None = None

    @property
    def label(self) -> str:
        return variant_label(self.params)

    def value(self, metric: str) -> float | None:
        """Mean of a scored metric, or an experiment metric (``opengrade.latency_p95_ms``)."""
        if self.result is None:
            return None
        scored = self.result.metrics
        if metric in scored:
            return scored[metric]
        return self.result.experiment_metrics.get(metric)


@dataclass
class SweepResult:
    """All runs of a sweep. ``leaderboard()`` ranks them, ``url`` opens them side by side."""

    name: str
    runs: list[SweepRun]
    url: str
    metric_names: list[str] = field(default_factory=list)

    @property
    def run_metric_names(self) -> list[str]:
        """Experiment-level metrics on any run: SDK ones first, then ``log_metrics`` keys."""
        names: list[str] = [*_RUN_METRICS]
        for result in self.results:
            for key in sorted(result.experiment_metrics):
                if key not in names:
                    names.append(key)
        return names

    @property
    def results(self) -> list[ExperimentResult]:
        return [run.result for run in self.runs if run.result is not None]

    @property
    def errors(self) -> list[SweepRun]:
        return [run for run in self.runs if run.error is not None]

    def _default_metric(self) -> str:
        if not self.metric_names:
            raise ValueError("no metric was scored in this sweep")
        return self.metric_names[0]

    def leaderboard(
        self, metric: str | None = None, *, lower_is_better: bool | None = None
    ) -> list[SweepRun]:
        """Runs sorted best first on ``metric`` (default: the first scored metric).

        Direction follows the metric name (latency/cost/error → lower is better) unless
        ``lower_is_better`` is given. Runs without a value come last.
        """
        key = metric or self._default_metric()
        lower = is_lower_better(key) if lower_is_better is None else lower_is_better
        scored = [run for run in self.runs if run.value(key) is not None]
        missing = [run for run in self.runs if run.value(key) is None]
        scored.sort(key=lambda run: run.value(key) or 0.0, reverse=not lower)
        return scored + missing

    def best(
        self, metric: str | None = None, *, lower_is_better: bool | None = None
    ) -> SweepRun | None:
        """The top run of ``leaderboard(metric)``, or ``None`` when nothing was scored."""
        ranked = self.leaderboard(metric, lower_is_better=lower_is_better)
        if not ranked or ranked[0].value(metric or self._default_metric()) is None:
            return None
        return ranked[0]

    def to_records(self) -> list[dict[str, Any]]:
        """One flat dict per run (params, metric means, run metrics, ids): ready for pandas."""
        rows: list[dict[str, Any]] = []
        for run in self.runs:
            row: dict[str, Any] = dict(run.params)
            for name in [*self.metric_names, *self.run_metric_names]:
                row[name] = run.value(name)
            row["experiment_id"] = run.result.id if run.result else None
            row["url"] = run.result.url if run.result else None
            row["error"] = run.error
            rows.append(row)
        return rows

    def summary(self, metric: str | None = None) -> str:
        """Plain-text leaderboard: one row per configuration, best first."""
        if not self.metric_names:
            lines = [f"Sweep {self.name}: {len(self.runs)} configurations, nothing scored"]
            lines.extend(f"  {run.label}: {run.error}" for run in self.errors)
            lines.append(f"  view: {self.url}")
            return "\n".join(lines)
        key = metric or self._default_metric()
        ranked = self.leaderboard(key)
        columns = [*self.metric_names, *self.run_metric_names]
        header = ("#", "configuration", *columns)
        rows: list[tuple[str, ...]] = []
        for index, run in enumerate(ranked, start=1):
            if run.result is None:
                rows.append((str(index), run.label, *(["-"] * len(columns))))
                continue
            rows.append(
                (str(index), run.label, *(_fmt_value(name, run.value(name)) for name in columns))
            )
        widths = [max(len(r[i]) for r in [header, *rows]) for i in range(len(header))]
        direction = "lower" if is_lower_better(key) else "higher"
        lines = [
            f"Sweep {self.name}: {len(self.runs)} configurations, ranked by {key} "
            f"({direction} is better), {len(self.errors)} failed"
        ]
        for row in [header, *rows]:
            lines.append("  " + "  ".join(c.ljust(w) for c, w in zip(row, widths, strict=True)))
        for run in self.errors:
            lines.append(f"  failed: {run.label}: {run.error}")
        lines.append(f"  view: {self.url}")
        return "\n".join(line.rstrip() for line in lines)

    def __str__(self) -> str:
        return self.summary()


def _fmt_value(name: str, value: float | None) -> str:
    if value is None:
        return "-"
    if name.endswith("_ms"):
        return f"{value:.0f}"
    return f"{value:.3f}"


def _variants(
    grid: Mapping[str, Sequence[Any]] | None, variants: Sequence[Mapping[str, Any]] | None
) -> list[dict[str, Any]]:
    if (grid is None) == (variants is None):
        raise ValueError("pass exactly one of grid= or variants=")
    expanded = expand_grid(grid) if grid is not None else [dict(v) for v in variants or []]
    if not expanded:
        raise ValueError("the sweep has no configurations")
    if len(expanded) > MAX_VARIANTS:
        raise ValueError(f"the sweep has {len(expanded)} configurations (max {MAX_VARIANTS})")
    for variant in expanded:
        if SWEEP_PARAM in variant:
            raise ValueError(f"{SWEEP_PARAM!r} is reserved for the sweep name")
    return expanded


def _bind(task: Callable[..., Any], params: dict[str, Any]) -> Callable[..., Any]:
    """``task(item, params)`` → ``task(item)`` for ``evaluate``."""

    def bound(item: Any) -> Any:
        return task(item, params)

    bound.__name__ = getattr(task, "__name__", "task")
    return bound


def _check_arity(fn: Callable[..., Any], label: str) -> None:
    try:
        signature = inspect.signature(fn)
    except (TypeError, ValueError):
        return
    try:
        signature.bind(object(), {})
    except TypeError:
        raise TypeError(
            f"{label} must accept (item, params): the sweep passes each configuration's "
            "params as the second argument"
        ) from None


def sweep(
    *,
    dataset: DatasetLike,
    task: Callable[[DatasetItemResponse, dict[str, Any]], Any] | None = None,
    retriever: Callable[[DatasetItemResponse, dict[str, Any]], Any] | None = None,
    grid: Mapping[str, Sequence[Any]] | None = None,
    variants: Sequence[Mapping[str, Any]] | None = None,
    metrics: Sequence[Metric] | None = None,
    name: str | None = None,
    params: Mapping[str, Any] | None = None,
    baseline: str | ExperimentResponse | ExperimentResult | None = None,
    k: int = 5,
    max_concurrency: int = 1,
    repeats: int = 1,
    group_by: str | None = None,
    project: str | None = None,
    version: str | None = None,
    git: bool | Mapping[str, Any] = True,
    task_type: str = "rag_qa",
    raise_on_error: bool = False,
    timeout: float = 600.0,
    og: Any = None,
    client: Client | None = None,
) -> SweepResult:
    """Run one experiment per configuration on the same test set and rank them.

    ``grid={"model": ["gemma", "llama"], "top_k": [3, 5]}`` runs every combination;
    ``variants=[{...}, {...}]`` runs an explicit list. ``task(item, params)`` (full pipeline,
    scored like ``evaluate``) or ``retriever(item, params)`` (retrieval only, scored like
    ``evaluate_retrieval`` with cutoff ``k``) receives each configuration's params.

    Every experiment stores its configuration (plus ``params`` shared by all, and
    ``params["sweep"] = name``) as its params, so the UI's Compare view can filter the sweep,
    plot any two metrics against each other and show what changed between two runs.
    Configurations run one after another (``max_concurrency`` applies within each run).
    A configuration that fails to run is reported in ``result.errors`` (or raised with
    ``raise_on_error=True``); the others still run.
    """
    if (task is None) == (retriever is None):
        raise ValueError("pass exactly one of task= or retriever=")
    if not 1 <= repeats <= MAX_REPEATS:
        raise ValueError(f"repeats must be between 1 and {MAX_REPEATS}")
    fn = task if task is not None else retriever
    assert fn is not None
    _check_arity(fn, "task" if task is not None else "retriever")
    configs = _variants(grid, variants)
    if params and SWEEP_PARAM in params:
        raise ValueError(f"{SWEEP_PARAM!r} is reserved for the sweep name")

    explicit_client = client is not None
    if client is None and og is not None:
        client = og.client
    if client is None:
        from opengrade._opengrade import current

        client = current().client
    project_id = _resolve_project(project, client, activate=not explicit_client)
    # Resolve (and upload, for inline rows) the test set once for every configuration.
    dataset_id = _resolve_dataset(client, project_id, dataset, task_type=task_type)
    stem = getattr(fn, "__name__", "")
    if not stem or stem == "<lambda>":
        stem = "sweep"
    sweep_name = name or f"{stem}-{time.strftime('%Y%m%d-%H%M%S')}"

    runs: list[SweepRun] = []
    for index, config in enumerate(configs, start=1):
        run = SweepRun(params=config)
        runs.append(run)
        stored = {**dict(params or {}), **config, SWEEP_PARAM: sweep_name}
        exp_name = f"{sweep_name} [{run.label}]"
        logger.info("opengrade sweep %s: %d/%d %s", sweep_name, index, len(configs), run.label)
        common: dict[str, Any] = {
            "dataset": dataset_id,
            "metrics": metrics,
            "name": exp_name,
            "params": stored,
            "baseline": baseline,
            "max_concurrency": max_concurrency,
            "project": project_id,
            "version": version,
            "git": git,
            "raise_on_error": raise_on_error,
            "timeout": timeout,
            "repeats": repeats,
            "group_by": group_by,
            "client": client,
        }
        try:
            if task is not None:
                run.result = evaluate(task=_bind(task, config), task_type=task_type, **common)
            else:
                assert retriever is not None
                run.result = evaluate_retrieval(retriever=_bind(retriever, config), k=k, **common)
        except Exception as exc:
            if raise_on_error:
                raise
            run.error = f"{type(exc).__name__}: {exc}"
            logger.warning("opengrade sweep %s: %s failed: %s", sweep_name, run.label, exc)

    metric_names: list[str] = []
    for run in runs:
        for metric in run.result.metrics if run.result else {}:
            if metric not in metric_names:
                metric_names.append(metric)
    ids = [run.result.id for run in runs if run.result is not None]
    url = experiments_compare_url(ui_base_url(client.base_url), ids, project_id)
    result = SweepResult(name=sweep_name, runs=runs, url=url, metric_names=metric_names)
    logger.info("opengrade sweep %s finished: %s", sweep_name, url)
    return result


__all__ = ["SweepResult", "SweepRun", "expand_grid", "is_lower_better", "sweep", "variant_label"]
