from __future__ import annotations

import csv
import hashlib
import inspect
import io
import json
import logging
import math
import numbers
import os
import re
import sys
import threading
import time
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from opentelemetry import trace as otel_trace
from opentelemetry.trace import Status, StatusCode

from opengrade import _config, _otel
from opengrade._async import run_sync
from opengrade._context import get_client, resolve_or_create_project
from opengrade._eval_run import bind_evaluation
from opengrade._http import OpengradeAPIError, OpengradeError
from opengrade._links import experiment_item_url, experiment_url, trace_url, ui_base_url
from opengrade._run_context import ACTIVE_RUN
from opengrade._trace import current_trace_id, truncate_value
from opengrade.client import Client
from opengrade.metrics import LocalMetric, Sample, Score, evaluate_metric
from opengrade.models import (
    DatasetItemResponse,
    DatasetResponse,
    EvaluateResponse,
    ExperimentCompareResponse,
    ExperimentItemOutputResponse,
    ExperimentResponse,
    ExperimentSummaryResponse,
    MetricComparisonResponse,
)

logger = logging.getLogger("opengrade")

# The experiment whose ``with`` block or item run is active, for opengrade.log_params/log_metrics.
ACTIVE_EXPERIMENT: ContextVar[Experiment | None] = ContextVar(
    "opengrade_active_experiment", default=None
)


Metric = str | Mapping[str, Any] | LocalMetric | Callable[..., Any]
"""A server metric kind (``"groundedness"``), an entry dict
(``{"kind": "hit_at_k", "threshold": 0.9, "config": {"k": 3}}``), a ``LocalMetric``
(``@opengrade.metric``) or a bare callable ``fn(sample)`` / ``fn(item, output)`` scored
locally."""

TASK_FAILED_EXPLANATION = "task raised before producing an output"

_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-?([0-9a-fA-F]{4}-?){3}[0-9a-fA-F]{12}$")
_ITEM_KEYS = frozenset({"input", "expected_output", "context", "metadata"})
_INPUT_KEYS = frozenset({"input", "question"})
_COLUMN_ALIASES = (
    ("question", "input"),
    ("expected_answer", "expected_output"),
)
_COLUMN_HELP = (
    "Required: 'input' (or alias 'question'). "
    "Optional: 'expected_output' (or 'expected_answer'), 'context', 'metadata'; "
    "other columns go into metadata (e.g. expected_doc_ids, must_contain)."
)
_UPSERT_CHUNK = 100
_MISSING: Any = object()


class DatasetColumnError(ValueError):
    """Raised when a dataset row or CSV header is missing required columns."""

    def __init__(
        self,
        *,
        missing: Sequence[str],
        found: Sequence[str],
        row_index: int | None = None,
        path: str | Path | None = None,
    ) -> None:
        self.missing = list(missing)
        self.found = list(found)
        self.row_index = row_index
        self.path = None if path is None else str(path)
        parts: list[str] = []
        if self.path is not None:
            parts.append(self.path)
        if row_index is not None:
            parts.append(f"row {row_index}")
        where = ": ".join(parts) if parts else "dataset"
        super().__init__(
            f"{where} missing column(s) {self.missing}; found {self.found}. {_COLUMN_HELP}"
        )


def _is_uuid(value: str) -> bool:
    return bool(_UUID_RE.match(value.strip()))


def _has_input_column(columns: Iterable[str | None] | None) -> bool:
    if columns is None:
        return False
    return bool(_INPUT_KEYS.intersection(c for c in columns if c))


def _sanitize_for_json(value: Any) -> Any:
    """Replace non-finite floats with None so payloads survive strict JSON encoders."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Mapping):
        return {k: _sanitize_for_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize_for_json(v) for v in value]
    return value


def _jsonable(value: Any) -> Any:
    """Round-trip through JSON so pydantic objects, numpy scalars etc. serialize."""
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    value = _sanitize_for_json(value)
    return json.loads(json.dumps(value, default=str, allow_nan=False))


_UPSERT_MAX_BYTES = 2 * 1024 * 1024  # under platform json_max_body_bytes (4 MiB)


def _chunk_by_bytes(
    items: list[Any],
    *,
    max_count: int,
    max_bytes: int,
) -> Iterator[list[Any]]:
    """Yield slices of ``items`` capped by count and approximate JSON byte size."""
    batch: list[Any] = []
    budget = 0
    for item in items:
        size = len(json.dumps(item, default=str, separators=(",", ":"), allow_nan=False).encode())
        if batch and (len(batch) >= max_count or budget + size > max_bytes):
            yield batch
            batch = []
            budget = 0
        batch.append(item)
        budget += size
    if batch:
        yield batch


def _digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


# ---------------------------------------------------------------------------
# Per-item run
# ---------------------------------------------------------------------------


@dataclass
class ItemRun:
    """One dataset item executed inside ``Experiment.run()``."""

    item: DatasetItemResponse
    output: Any = None
    has_output: bool = False
    error: str | None = None
    trace_id: str | None = None
    latency_ms: float | None = None
    scores: dict[str, float | None] = field(default_factory=dict)
    metric_errors: dict[str, str] = field(default_factory=dict)
    results: dict[str, Score] = field(default_factory=dict)
    documents: list[dict[str, Any]] | None = None
    context: dict[str, Any] = field(default_factory=dict)
    # Stable UI links, filled in by ``Experiment.finish()``.
    url: str | None = None
    trace_url: str | None = None
    _explicit_output: bool = field(default=False, repr=False)

    def log(
        self,
        output: Any = _MISSING,
        *,
        documents: Sequence[Mapping[str, Any]] | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> None:
        """Record the item's output (and optionally retrieved documents / extra context).

        An explicit ``log(output)`` wins over values captured from ``opengrade.set_output``.
        """
        if output is not _MISSING:
            self.output = output
            self.has_output = True
            self._explicit_output = True
        if documents is not None:
            self.documents = [dict(doc) for doc in documents]
        if context is not None:
            self.context.update(context)

    def _capture_output(self, value: object) -> None:
        if not self._explicit_output:
            self.output = value
            self.has_output = True

    def _capture_documents(self, documents: list[dict[str, Any]]) -> None:
        # Last retrieval stage wins (retriever → reranker), as on the server.
        self.documents = documents


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


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
    def local_metrics(self) -> dict[str, float | None]:
        names: list[str] = []
        for run in self.items:
            for name in run.scores:
                if name not in names:
                    names.append(name)
        means: dict[str, float | None] = {}
        for name in names:
            values = [v for run in self.items if (v := run.scores.get(name)) is not None]
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

    def _comparison_by_name(self) -> dict[str, MetricComparisonResponse]:
        if self.comparison is None:
            return {}
        rows: dict[str, MetricComparisonResponse] = {}
        for row in self.comparison.metrics:
            key = row.evaluator_name or row.evaluator_id or ""
            rows.setdefault(key, row)
        return rows

    def summary(self) -> str:
        """Plain-text table: one row per metric with the baseline delta, then experiment metrics."""
        n = len(self.items)
        head = (
            f"Experiment {self.experiment.name} ({self.id}): "
            f"{n} item{'s' if n != 1 else ''}, {len(self.errors)} errors, "
            f"status={self.status}"
        )
        compared = self._comparison_by_name()
        rows: list[tuple[str, str, str, str]] = []
        seen: set[str] = set()
        if self.server_summary is not None:
            for ev in self.server_summary.evaluators:
                name = ev.evaluator_name or ev.evaluator_id or "?"
                seen.add(name)
                rows.append(
                    (
                        name,
                        _fmt(ev.mean_score),
                        _fmt(ev.pass_rate),
                        _fmt_delta(compared.get(name)),
                    )
                )
        for name, mean in self.local_metrics.items():
            if name not in seen:  # submission failed: show the in-process mean
                rows.append((f"{name} (local only)", _fmt(mean), "-", ""))
        lines = [head]
        if rows:
            header = ("metric", "mean", "pass_rate", "vs baseline" if compared else "")
            widths = [max(len(r[i]) for r in [header, *rows]) for i in range(4)]
            for row in [header, *rows]:
                lines.append("  " + "  ".join(c.ljust(w) for c, w in zip(row, widths, strict=True)))
        else:
            lines.append("  (no metrics scored)")
        lines.extend(self._experiment_metric_lines())
        lines.append(f"  view: {self.url}")
        for run in self.errors[:_MAX_ERROR_LINKS]:
            lines.append(f"  error: {run.trace_url or run.url or run.item.id}")
        return "\n".join(line.rstrip() for line in lines)

    def __str__(self) -> str:
        return self.summary()


_MAX_ERROR_LINKS = 5


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


# ---------------------------------------------------------------------------
# Experiment
# ---------------------------------------------------------------------------


class Experiment:
    """A live experiment: iterate ``items()``, wrap each in ``run(item)``, then finish.

    Usable as a context manager — a clean exit calls ``finish()`` and stores the
    outcome on ``.result``; an exception skips scoring.
    """

    def __init__(
        self,
        *,
        client: Client,
        experiment: ExperimentResponse,
        items: list[DatasetItemResponse],
        metrics_set_id: str | None,
        score_on_server: bool,
        local_metrics: list[LocalMetric],
        baseline_id: str | None,
    ) -> None:
        self._client = client
        self.experiment = experiment
        self._items = items
        self._items_by_id = {item.id: item for item in items}
        self._metrics_set_id = metrics_set_id
        self._score_on_server = score_on_server
        self._local_metrics = local_metrics
        self.baseline_id = baseline_id
        self._records: dict[str, ItemRun] = {}
        self._lock = threading.Lock()
        self.result: ExperimentResult | None = None
        self._metrics_logged = False
        self._context_token: Token[Experiment | None] | None = None

    @property
    def id(self) -> str:
        return self.experiment.id

    @property
    def name(self) -> str:
        return self.experiment.name

    @property
    def dataset_id(self) -> str:
        return str(self.experiment.dataset_id)

    @property
    def url(self) -> str:
        return experiment_url(self._ui_base, self.id, self.experiment.project_id or None)

    @property
    def _ui_base(self) -> str:
        return ui_base_url(self._client.base_url)

    @property
    def params(self) -> dict[str, Any]:
        """Stored model config: ``params``, or the app config snapshot when one was bound."""
        return dict(self.experiment.experiment_model_config)

    def log_params(self, **params: Any) -> dict[str, Any]:
        """Merge ``params`` into the stored model config and return the merged config.

        Allowed until the experiment is scored, and not for experiments created from an
        app config: the server answers 409 (``OpengradeAPIError``) in both cases.
        """
        if not params:
            raise ValueError("log_params needs at least one param")
        updated = self._client.experiments.update_params(self.id, _jsonable(params))
        with self._lock:
            self.experiment = updated
            return dict(updated.experiment_model_config)

    def log_metrics(self, metrics: Mapping[str, float]) -> dict[str, float]:
        """Upsert experiment-level scalars (MLflow-style: one final value per key).

        They show up in the summary, are compared with the baseline and can gate a
        release (``experiment_metrics: {cost_usd: {max: 2}}``). Returns all of them.
        """
        if not metrics:
            raise ValueError("log_metrics needs at least one metric")
        for key, value in metrics.items():
            if isinstance(value, bool) or not isinstance(value, numbers.Real):
                raise ValueError(f"metric {key!r} must be a number, got {value!r}")
        stored = self._client.experiments.log_metrics(
            self.id, {key: float(value) for key, value in metrics.items()}
        )
        self._metrics_logged = True
        return stored

    def items(self) -> list[DatasetItemResponse]:
        return list(self._items)

    def run_task(
        self,
        task: Callable[[DatasetItemResponse], Any],
        *,
        max_concurrency: int = 1,
        raise_on_error: bool = False,
    ) -> None:
        """Run ``task(item)`` on every item inside ``run(item)``, logging its return value."""
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be >= 1")

        def work(item: DatasetItemResponse) -> None:
            try:
                with self.run(item) as run:
                    output = task(item)
                    if inspect.isawaitable(output):
                        output = run_sync(output)
                    if output is not None or not run.has_output:
                        run.log(output)
            except Exception as exc:
                if raise_on_error:
                    raise
                logger.warning("opengrade: task failed on item %s: %s", item.id, exc)

        if max_concurrency == 1:
            for item in self._items:
                work(item)
            return
        with ThreadPoolExecutor(max_workers=max_concurrency) as pool:
            for future in [pool.submit(work, item) for item in self._items]:
                future.result()

    def __enter__(self) -> Experiment:
        if self._context_token is not None:
            raise RuntimeError("experiment is already active in a with block")
        self._context_token = ACTIVE_EXPERIMENT.set(self)
        return self

    def __exit__(self, exc_type: type[BaseException] | None, *_exc: object) -> None:
        if self._context_token is not None:
            ACTIVE_EXPERIMENT.reset(self._context_token)
            self._context_token = None
        if exc_type is not None:
            _otel.flush()
            logger.warning("opengrade experiment %s aborted; skipping scoring", self.id)
            return
        if self.result is None:
            self.finish()

    @contextmanager
    def run(self, item: DatasetItemResponse | str) -> Iterator[ItemRun]:
        """Run one item: opens a root span bound to (experiment, item) and records output.

        Inside the block call ``run.log(output)`` or ``opengrade.set_output(...)``;
        ``opengrade.set_retrieval_documents`` is captured too.
        """
        resolved = self._resolve_item(item)
        record = ItemRun(item=resolved)
        tracer = otel_trace.get_tracer("opengrade")
        token = ACTIVE_RUN.set(record)
        experiment_token = ACTIVE_EXPERIMENT.set(self)
        started = time.perf_counter()
        try:
            with tracer.start_as_current_span(
                f"opengrade.eval {self.name}", record_exception=False, set_status_on_exception=False
            ) as span:
                span.set_attribute("openinference.span.kind", "CHAIN")
                bind_evaluation(experiment_id=self.id, dataset_item_id=resolved.id)
                span.set_attribute("input.value", truncate_value(resolved.input))
                record.trace_id = current_trace_id() if span.is_recording() else None
                try:
                    yield record
                except BaseException as exc:
                    record.error = f"{type(exc).__name__}: {exc}"
                    span.record_exception(exc)
                    span.set_status(Status(StatusCode.ERROR, str(exc)))
                    raise
                finally:
                    if record.has_output:
                        span.set_attribute("output.value", truncate_value(record.output))
        finally:
            record.latency_ms = (time.perf_counter() - started) * 1000.0
            ACTIVE_RUN.reset(token)
            ACTIVE_EXPERIMENT.reset(experiment_token)
            if record.error is None:
                self._score_locally(record)
            with self._lock:
                self._records[resolved.id] = record

    def _resolve_item(self, item: DatasetItemResponse | str) -> DatasetItemResponse:
        item_id = item if isinstance(item, str) else item.id
        found = self._items_by_id.get(item_id)
        if found is None:
            raise ValueError(f"item {item_id} is not in dataset {self.dataset_id}")
        return found

    def _score_locally(self, record: ItemRun) -> None:
        sample = _sample_from(record)
        for metric in self._local_metrics:
            name = _local_name(metric)
            try:
                result = evaluate_metric(metric, sample, item=record.item)
            except Exception as exc:  # a broken metric must not sink the run
                logger.warning(
                    "opengrade local metric %s failed on item %s: %s", name, record.item.id, exc
                )
                record.scores[name] = None
                record.metric_errors[name] = f"{type(exc).__name__}: {exc}"
                continue
            record.results[name] = result
            record.scores[name] = result.value

    def _submit_local_scores(self, records: list[ItemRun]) -> bool:
        """Send local metric scores to the platform; False (with a warning) on failure."""
        if not self._local_metrics:
            return False
        payload = []
        for metric in self._local_metrics:
            name = _local_name(metric)
            results = []
            for record in records:
                result: dict[str, Any] = {"dataset_item_id": record.item.id}
                if record.error is not None:
                    # Same rule as server metrics for a missing output: a failure, not N/A.
                    result.update(
                        score=0.0,
                        label="FAIL",
                        explanation=f"{TASK_FAILED_EXPLANATION}: {record.error}"[:4000],
                    )
                elif name in record.metric_errors:
                    result.update(label="ERROR", explanation=record.metric_errors[name][:4000])
                else:
                    score = record.results.get(name, Score())
                    result["score"] = score.value
                    if score.label is not None:
                        result["label"] = score.label
                    if score.explanation is not None:
                        result["explanation"] = score.explanation[:4000]
                    if score.metadata:
                        result["metadata"] = score.metadata
                results.append(result)
            entry: dict[str, Any] = {"name": name, "results": results}
            if metric.threshold is not None:
                entry["threshold"] = metric.threshold
            if metric.config:
                entry["config"] = _jsonable(dict(metric.config))
            payload.append(entry)
        try:
            for chunk in _chunk_by_bytes(
                payload, max_count=_UPSERT_CHUNK, max_bytes=_UPSERT_MAX_BYTES
            ):
                self._client.experiments.submit_client_results(self.id, chunk)
        except OpengradeError as exc:
            logger.warning(
                "opengrade: could not submit local metrics for experiment %s: %s", self.id, exc
            )
            return False
        return True

    def _log_auto_metrics(self, records: list[ItemRun]) -> None:
        try:
            self.log_metrics(_auto_metrics(records))
        except OpengradeError as exc:
            logger.warning(
                "opengrade: could not log run metrics for experiment %s: %s", self.id, exc
            )

    def runs(self) -> list[ItemRun]:
        with self._lock:
            return list(self._records.values())

    def finish(
        self,
        *,
        timeout: float = 600.0,
        bind_timeout: float = 30.0,
        poll_interval: float = 1.0,
    ) -> ExperimentResult:
        """Write outputs, score with the metrics set, compare with the baseline."""
        if self.result is not None:
            return self.result
        records = self.runs()
        if not records:
            raise RuntimeError(f"experiment {self.id}: no items were run")

        stored = self._await_trace_binding(records, bind_timeout, poll_interval)
        payload = [_output_entry(record, stored.get(record.item.id)) for record in records]
        for chunk in _chunk_by_bytes(payload, max_count=_UPSERT_CHUNK, max_bytes=_UPSERT_MAX_BYTES):
            try:
                self._client.experiments.upsert_outputs(self.id, chunk)
            except OpengradeError as exc:
                logger.warning(
                    "opengrade: could not upsert outputs for experiment %s: %s", self.id, exc
                )

        # After the outputs: client runs record the inputs fingerprint they scored.
        submitted = self._submit_local_scores(records)
        self._log_auto_metrics(records)

        evaluation: EvaluateResponse | None = None
        server_summary: ExperimentSummaryResponse | None = None
        comparison: ExperimentCompareResponse | None = None
        if self._score_on_server:
            evaluation = self._client.experiments.evaluate_pack(
                self.id,
                metrics_set_id=self._metrics_set_id,
                poll_interval=poll_interval,
                timeout=timeout,
            )
        scored = evaluation is not None or submitted
        if scored:
            server_summary = self._client.experiments.summary(self.id)
        elif self._metrics_logged:
            try:
                server_summary = self._client.experiments.summary(self.id)
            except OpengradeError as exc:
                logger.warning(
                    "opengrade: could not fetch summary for experiment %s: %s", self.id, exc
                )
        # Compare needs evaluator runs on both sides; experiment metrics ride along.
        if scored and self.baseline_id is not None:
            try:
                comparison = self._client.experiments.compare(self.id, self.baseline_id)
            except OpengradeError as exc:
                logger.warning(
                    "opengrade: compare with baseline %s failed: %s", self.baseline_id, exc
                )

        project_id = self.experiment.project_id or None
        for record in records:
            record.url = experiment_item_url(self._ui_base, self.id, record.item.id, project_id)
            if record.trace_id:
                record.trace_url = trace_url(self._ui_base, record.trace_id, project_id)

        self.result = ExperimentResult(
            experiment=evaluation.experiment if evaluation else self.experiment,
            url=self.url,
            items=records,
            evaluation=evaluation,
            server_summary=server_summary,
            comparison=comparison,
            baseline_id=self.baseline_id,
        )
        announce(self.result)
        return self.result

    def _await_trace_binding(
        self, records: list[ItemRun], bind_timeout: float, poll_interval: float
    ) -> dict[str, ExperimentItemOutputResponse]:
        """Wait until OTLP-ingested traces are bound, so our PUT lands last."""
        traced = {r.item.id: r.trace_id for r in records if r.trace_id}
        if traced and _otel._INITIALIZED:
            _otel.flush()
        else:
            traced = {}
        deadline = time.monotonic() + bind_timeout
        while True:
            stored = {
                str(o.dataset_item_id): o for o in self._client.experiments.list_outputs(self.id)
            }
            pending = [
                item_id
                for item_id, trace_id in traced.items()
                if (o := stored.get(item_id)) is None
                or o.metadata.get("source_trace_id") != trace_id
            ]
            if not pending:
                return stored
            if time.monotonic() >= deadline:
                logger.warning(
                    "opengrade: %d/%d traces not bound to experiment %s after %.0fs; "
                    "writing outputs without their trace context",
                    len(pending),
                    len(traced),
                    self.id,
                    bind_timeout,
                )
                return stored
            time.sleep(poll_interval)


def _sample_from(record: ItemRun) -> Sample:
    item = record.item
    return Sample(
        input=item.input,
        output=record.output,
        expected=item.expected_output,
        documents=[dict(doc) for doc in record.documents or []],
        context=dict(record.context),
        metadata=dict(item.metadata),
        trace_id=record.trace_id,
        item_id=item.id,
    )


def _nearest_rank(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    return ordered[max(1, math.ceil(percentile / 100.0 * len(ordered))) - 1]


def _auto_metrics(records: list[ItemRun]) -> dict[str, float]:
    """Run-level numbers logged on every finish: error share and nearest-rank percentiles of
    task wall-clock latency over items that did not fail."""
    metrics: dict[str, float] = {
        "opengrade.error_rate": sum(r.error is not None for r in records) / len(records)
    }
    latencies = [r.latency_ms for r in records if r.error is None and r.latency_ms is not None]
    if latencies:
        metrics["opengrade.latency_p50_ms"] = _nearest_rank(latencies, 50.0)
        metrics["opengrade.latency_p95_ms"] = _nearest_rank(latencies, 95.0)
    return metrics


def _output_entry(record: ItemRun, stored: ExperimentItemOutputResponse | None) -> dict[str, Any]:
    entry: dict[str, Any] = {"dataset_item_id": record.item.id}
    if record.has_output:
        entry["actual_output"] = _jsonable(record.output)

    # Trace-derived context (tokens, cost, documents) first; client capture fills gaps;
    # anything passed to run.log(context=...) wins.
    context: dict[str, Any] = {}
    if stored is not None and isinstance(stored.context, dict):
        context.update(stored.context)
    if record.documents and not context.get("documents"):
        context["documents"] = _jsonable(record.documents)
    if record.latency_ms is not None:
        context.setdefault("latency_ms", record.latency_ms)
    context.update(_jsonable(record.context))
    if context:
        entry["context"] = context

    metadata: dict[str, Any] = dict(stored.metadata) if stored is not None else {}
    if record.trace_id:
        metadata.setdefault("source_trace_id", record.trace_id)
    if record.error is not None:
        metadata["error"] = record.error
    entry["metadata"] = metadata
    return entry


# ---------------------------------------------------------------------------
# Resolution helpers
# ---------------------------------------------------------------------------

DatasetLike = (
    str | Path | DatasetResponse | Sequence[Mapping[str, Any]] | Iterable[Mapping[str, Any]] | Any
)
"""Dataset name, id, ``DatasetResponse``, path to CSV/JSON/JSONL, list/iterable of
dicts, pandas DataFrame, or Polars DataFrame."""


def _resolve_project(
    project: str | None,
    client: Client,
    *,
    activate: bool,
) -> str:
    if project is None:
        return _config.resolve_project_id()
    if _is_uuid(project):
        return project
    created = resolve_or_create_project(project, client, activate=activate)
    if created is None:
        raise ValueError(f"could not resolve project {project!r}: platform unreachable")
    return created.id


def _canonicalize_row(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    for alias, canonical in _COLUMN_ALIASES:
        if alias not in out:
            continue
        if canonical not in out or out[canonical] is None:
            out[canonical] = out[alias]
        del out[alias]
    return out


def _load_file_records(path: Path) -> list[dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError(f"dataset file must be UTF-8: {path}") from exc
    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        records: list[dict[str, Any]] = []
        for line_no, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                obj = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}: JSONL line {line_no} is not valid JSON") from exc
            if not isinstance(obj, Mapping):
                raise TypeError(f"{path}: JSONL line {line_no} must be a JSON object")
            records.append(_jsonable(dict(obj)))
        return records
    if suffix == ".json" or text.lstrip().startswith("["):
        data = json.loads(text)
        if not isinstance(data, list):
            raise ValueError(f"{path}: JSON dataset must be an array of objects")
        if not all(isinstance(row, Mapping) for row in data):
            raise TypeError(f"{path}: JSON dataset must contain objects")
        return [_jsonable(dict(row)) for row in data]
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise ValueError(f"{path}: CSV has no header")
    found = [c for c in reader.fieldnames if c]
    if not _has_input_column(found):
        raise DatasetColumnError(
            missing=["input (or question)"],
            found=found,
            path=path,
        )
    return [_jsonable(dict(row)) for row in reader]


def _mapping_rows(rows: Iterable[Any], *, label: str) -> list[dict[str, Any]]:
    materialised = list(rows)
    if not all(isinstance(row, Mapping) for row in materialised):
        raise TypeError(f"{label} must contain dicts")
    return [_jsonable(dict(row)) for row in materialised]


def _records_from(dataset: Any) -> list[dict[str, Any]] | None:
    if isinstance(dataset, Path):
        if not dataset.is_file():
            raise ValueError(f"dataset path does not exist: {dataset}")
        return _load_file_records(dataset)
    # Polars before pandas: Polars uses to_dicts(); pandas uses to_json(orient=...).
    if callable(getattr(dataset, "to_dicts", None)) and hasattr(dataset, "columns"):
        return _mapping_rows(dataset.to_dicts(), label="polars DataFrame")
    if hasattr(dataset, "to_json") and hasattr(dataset, "columns"):  # pandas DataFrame
        records = json.loads(dataset.to_json(orient="records", date_format="iso"))
        return [dict(r) for r in records]
    if isinstance(dataset, Sequence) and not isinstance(dataset, (str, bytes)):
        return _mapping_rows(dataset, label="dataset list")
    if isinstance(dataset, Iterable) and not isinstance(dataset, (str, bytes, Mapping)):
        return _mapping_rows(dataset, label="dataset iterable")
    return None


def _parse_json_column(key: str, value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"dataset column {key!r} must be valid JSON: {exc.msg}") from exc


def _normalize_item_value(key: str, value: Any) -> Any:
    """CSV empty cells become ``None``; ``metadata``/``context`` strings are JSON."""
    if value == "":
        return None
    if key in ("metadata", "context") and isinstance(value, str):
        return _parse_json_column(key, value)
    return value


def _item_body(row: dict[str, Any], index: int) -> dict[str, Any]:
    raw_keys = sorted(row)
    row = _canonicalize_row(row)
    if "input" not in row or row.get("input") in (None, ""):
        raise DatasetColumnError(
            missing=["input (or question)"],
            found=raw_keys,
            row_index=index,
        )
    normalized = {k: _normalize_item_value(k, v) for k, v in row.items()}
    body = {k: normalized[k] for k in _ITEM_KEYS if normalized.get(k) is not None}
    extras = {
        k: v for k, v in normalized.items() if k not in _ITEM_KEYS and v is not None and v != ""
    }
    if extras:
        body["metadata"] = {**extras, **dict(body.get("metadata") or {})}
    return body


def _inline_dataset_id(
    client: Client,
    project_id: str,
    records: list[dict[str, Any]],
    *,
    task_type: str,
) -> str:
    if not records:
        raise ValueError("dataset is empty")
    bodies = [_item_body(row, i) for i, row in enumerate(records)]
    # Content-addressed name: re-running on the same rows reuses the dataset, so runs
    # stay comparable against each other.
    name = f"inline-{_digest([task_type, bodies])[:12]}"
    expected = len(bodies)
    for existing in client.datasets.list(project_id):
        if existing.name != name:
            continue
        detail = client.datasets.get(existing.id)
        have = len(detail.items)
        if have == expected:
            return existing.id
        if have > expected:
            # Unexpected extra rows: mint a fresh name rather than reuse a bad set.
            name = f"{name}-r{_digest(existing.id)[:6]}"
            break
        # Partial create from a previous interrupted upload — resume remaining items.
        client.datasets.ensure_items(existing.id, bodies)
        logger.info("opengrade resumed dataset %s (%d → %d items)", existing.name, have, expected)
        return existing.id
    created = client.datasets.create_with_items(
        project_id,
        name=name,
        items=bodies,
        task_type=task_type,
        description="Created by opengrade.evaluate() from in-memory rows",
    )
    logger.info("opengrade created dataset %s (%d items)", name, len(bodies))
    return created.id


def _resolve_dataset(
    client: Client, project_id: str, dataset: DatasetLike, *, task_type: str
) -> str:
    if isinstance(dataset, DatasetResponse):
        return dataset.id
    if isinstance(dataset, Path):
        if not dataset.is_file():
            raise ValueError(f"dataset path does not exist: {dataset}")
        return _inline_dataset_id(
            client, project_id, _load_file_records(dataset), task_type=task_type
        )
    if isinstance(dataset, str):
        if _is_uuid(dataset):
            return dataset
        # Existing file path wins over a registered dataset name (e.g. "gold.csv").
        if os.path.isfile(dataset):
            return _inline_dataset_id(
                client, project_id, _load_file_records(Path(dataset)), task_type=task_type
            )
        matches = [d for d in client.datasets.list(project_id) if d.name == dataset]
        if not matches:
            raise ValueError(f"no dataset named {dataset!r} in project {project_id}")
        return max(matches, key=lambda d: d.version).id

    records = _records_from(dataset)
    if records is None:
        raise TypeError(
            "dataset must be a name, id, DatasetResponse, file path, list/iterable of "
            f"dicts, pandas DataFrame or Polars DataFrame; got {type(dataset).__name__}"
        )
    return _inline_dataset_id(client, project_id, records, task_type=task_type)


def _local_name(metric: LocalMetric) -> str:
    assert metric.name is not None  # filled by _split_metrics
    return metric.name


def _split_metrics(
    metrics: Sequence[Metric],
) -> tuple[list[dict[str, Any]], list[LocalMetric]]:
    server: list[dict[str, Any]] = []
    local: list[LocalMetric] = []
    for index, metric in enumerate(metrics):
        if isinstance(metric, str):
            server.append({"kind": metric.strip()})
        elif isinstance(metric, Mapping):
            if not metric.get("kind"):
                raise ValueError(f"metric dict needs a 'kind': {metric!r}")
            server.append(dict(metric))
        elif isinstance(metric, LocalMetric) or callable(metric):
            spec = metric if isinstance(metric, LocalMetric) else LocalMetric(fn=metric)
            name = spec.name or getattr(spec.fn, "__name__", "") or ""
            if not name or name == "<lambda>":
                name = f"metric_{index}"
            local.append(replace(spec, name=name, config=dict(spec.config)))
        else:
            raise TypeError(f"unsupported metric {metric!r}")
    kinds = [entry["kind"] for entry in server]
    if len(set(kinds)) != len(kinds):
        raise ValueError(f"duplicate metric kinds: {kinds}")
    names = [_local_name(m) for m in local]
    if len(set(names)) != len(names):
        raise ValueError(f"duplicate local metric names: {names}")
    return server, local


def _resolve_metrics_set(client: Client, project_id: str, requested: list[dict[str, Any]]) -> str:
    """Find or create a metrics set holding exactly ``requested`` (enabled).

    Thresholds/config default to the project's default set, so ``"hit_at_k"``
    behaves like it does in the UI.
    """
    sets = client.metrics_sets.list(project_id)
    defaults: dict[str, dict[str, Any]] = {}
    default_set = next((s for s in sets if s.is_project_default), None)
    if default_set is not None:
        for e in client.metrics_sets.get(default_set.id).entries:
            defaults[e.kind] = {"threshold": e.threshold, "config": dict(e.config)}

    entries: list[dict[str, Any]] = []
    for spec in requested:
        base = defaults.get(spec["kind"], {"threshold": None, "config": {}})
        entry = {"kind": spec["kind"], "enabled": True, **base}
        entry.update({k: v for k, v in spec.items() if k != "kind"})
        entries.append(entry)

    label = "+".join(e["kind"] for e in entries)[:150]
    name = f"sdk:{label}@{_digest(entries)[:8]}"
    for existing in sets:
        if existing.name == name:
            return existing.id
    try:
        created = client.metrics_sets.create(
            project_id,
            name=name,
            entries=entries,
            description="Created by opengrade.evaluate()",
        )
    except OpengradeAPIError as exc:
        if exc.status != 409:
            raise
        # Created concurrently by another process — use theirs.
        for existing in client.metrics_sets.list(project_id):
            if existing.name == name:
                return existing.id
        raise
    return created.id


def _resolve_baseline(
    client: Client,
    project_id: str,
    baseline: str | ExperimentResponse | ExperimentResult | None,
    *,
    dataset_id: str,
) -> str | None:
    if baseline is None:
        return None
    if isinstance(baseline, ExperimentResult):
        return baseline.id
    if isinstance(baseline, ExperimentResponse):
        return baseline.id
    if _is_uuid(baseline):
        return baseline
    matches = [e for e in client.experiments.list(project_id) if e.name == baseline]
    if not matches:
        raise ValueError(f"no baseline experiment named {baseline!r} in project {project_id}")
    same_dataset = [e for e in matches if str(e.dataset_id) == dataset_id]
    pool = same_dataset or matches
    return max(pool, key=lambda e: str(e.created_at or "")).id


def _default_name(task: Callable[..., Any] | None) -> str:
    stem = getattr(task, "__name__", "") if task is not None else ""
    if not stem or stem == "<lambda>":
        stem = "experiment"
    return f"{stem}-{time.strftime('%Y%m%d-%H%M%S')}"


def _active_experiment() -> Experiment:
    exp = ACTIVE_EXPERIMENT.get()
    if exp is None:
        raise RuntimeError(
            "no active experiment: call inside `with opengrade.start_experiment(...)` "
            "or inside an item run (exp.run, run_task or an evaluate() task)"
        )
    return exp


def log_params(**params: Any) -> dict[str, Any]:
    """``Experiment.log_params`` on the active experiment."""
    return _active_experiment().log_params(**params)


def log_metrics(metrics: Mapping[str, float]) -> dict[str, float]:
    """``Experiment.log_metrics`` on the active experiment."""
    return _active_experiment().log_metrics(metrics)


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def start_experiment(
    name: str | None = None,
    *,
    dataset: DatasetLike,
    metrics: Sequence[Metric] | None = None,
    params: Mapping[str, Any] | None = None,
    baseline: str | ExperimentResponse | ExperimentResult | None = None,
    project: str | None = None,
    version: str | None = None,
    task_type: str = "rag_qa",
    app_config_id: str | None = None,
    app_config_alias: str | None = None,
    client: Client | None = None,
) -> Experiment:
    """Create an experiment and return it for a manual loop.

    ``metrics=None`` scores with the project's default metrics set; a list scores
    with exactly those server kinds (plus local callables). ``baseline`` is an
    experiment id, name (latest wins) or a previous result. With an app config the
    server snapshots it as the experiment's params (``exp.params``), replacing
    ``params``.
    """
    explicit_client = client is not None
    client = client or get_client()
    project_id = _resolve_project(project, client, activate=not explicit_client)
    dataset_id = _resolve_dataset(client, project_id, dataset, task_type=task_type)

    server_metrics: list[dict[str, Any]] = []
    local_metrics: list[LocalMetric] = []
    if metrics is not None:
        server_metrics, local_metrics = _split_metrics(metrics)
    score_on_server = metrics is None or bool(server_metrics)
    metrics_set_id = (
        _resolve_metrics_set(client, project_id, server_metrics) if server_metrics else None
    )
    baseline_id = _resolve_baseline(client, project_id, baseline, dataset_id=dataset_id)

    experiment = client.experiments.create(
        project_id,
        name=name or _default_name(None),
        dataset_id=dataset_id,
        model_config=_jsonable(dict(params or {})),
        version=version,
        baseline_experiment_id=baseline_id,
        app_config_id=app_config_id,
        app_config_alias=app_config_alias,
        metrics_set_id=metrics_set_id,
    )
    items = client.datasets.get(dataset_id).items
    if not items:
        raise ValueError(f"dataset {dataset_id} has no items")
    exp = Experiment(
        client=client,
        experiment=experiment,
        items=items,
        metrics_set_id=metrics_set_id,
        score_on_server=score_on_server,
        local_metrics=local_metrics,
        baseline_id=baseline_id,
    )
    logger.info("opengrade experiment %s started: %s", experiment.name, exp.url)
    return exp


def evaluate(
    *,
    dataset: DatasetLike,
    task: Callable[[DatasetItemResponse], Any],
    metrics: Sequence[Metric] | None = None,
    name: str | None = None,
    params: Mapping[str, Any] | None = None,
    baseline: str | ExperimentResponse | ExperimentResult | None = None,
    max_concurrency: int = 1,
    project: str | None = None,
    version: str | None = None,
    task_type: str = "rag_qa",
    app_config_id: str | None = None,
    app_config_alias: str | None = None,
    raise_on_error: bool = False,
    timeout: float = 600.0,
    client: Client | None = None,
) -> ExperimentResult:
    """Run ``task`` on every dataset item, score it and return the result.

    ``task(item)`` gets a ``DatasetItemResponse`` (``item.input``,
    ``item.expected_output``, ``item.metadata``) and returns the output. Calls to
    ``opengrade.set_retrieval_documents`` inside it feed retrieval metrics. A task that
    raises is recorded as an item error (unless ``raise_on_error``).
    """
    if max_concurrency < 1:
        raise ValueError("max_concurrency must be >= 1")
    exp = start_experiment(
        name or _default_name(task),
        dataset=dataset,
        metrics=metrics,
        params=params,
        baseline=baseline,
        project=project,
        version=version,
        task_type=task_type,
        app_config_id=app_config_id,
        app_config_alias=app_config_alias,
        client=client,
    )
    exp.run_task(task, max_concurrency=max_concurrency, raise_on_error=raise_on_error)
    result = exp.finish(timeout=timeout)
    logger.info("opengrade experiment %s finished: %s", result.experiment.name, result.url)
    return result


__all__ = [
    "Experiment",
    "ExperimentResult",
    "ItemRun",
    "LocalMetric",
    "Metric",
    "evaluate",
    "log_metrics",
    "log_params",
    "start_experiment",
]
