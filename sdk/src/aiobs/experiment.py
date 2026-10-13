from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from typing import Any

from opentelemetry import trace as otel_trace
from opentelemetry.trace import Status, StatusCode

from aiobs import _config, _otel
from aiobs._context import get_client, set_project
from aiobs._eval_run import bind_evaluation
from aiobs._http import AiobsAPIError
from aiobs._run_context import ACTIVE_RUN
from aiobs._trace import current_trace_id, truncate_value
from aiobs.client import Client
from aiobs.metrics import LocalMetric, Sample, Score, evaluate_metric
from aiobs.models import (
    DatasetItemResponse,
    DatasetResponse,
    EvaluateResponse,
    ExperimentCompareResponse,
    ExperimentItemOutputResponse,
    ExperimentResponse,
    ExperimentSummaryResponse,
    MetricComparisonResponse,
)

logger = logging.getLogger("aiobs")


Metric = str | Mapping[str, Any] | LocalMetric | Callable[..., Any]
"""A server metric kind (``"groundedness"``), an entry dict
(``{"kind": "hit_at_k", "threshold": 0.9, "config": {"k": 3}}``), a ``LocalMetric``
(``@aiobs.metric``) or a bare callable ``fn(sample)`` / ``fn(item, output)`` scored
locally."""

TASK_FAILED_EXPLANATION = "task raised before producing an output"

_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-?([0-9a-fA-F]{4}-?){3}[0-9a-fA-F]{12}$")
_ITEM_KEYS = frozenset({"input", "expected_output", "context", "metadata"})
_UPSERT_CHUNK = 100
_MISSING: Any = object()


def _is_uuid(value: str) -> bool:
    return bool(_UUID_RE.match(value.strip()))


def _jsonable(value: Any) -> Any:
    """Round-trip through JSON so pydantic objects, numpy scalars etc. serialize."""
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.loads(json.dumps(value, default=str))


def _digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def ui_base_url(api_base_url: str) -> str:
    """UI host for result links: ``AIOBS_UI_URL``, else the API host (``aiobs ui``)."""
    override = os.getenv("AIOBS_UI_URL")
    if override and override.strip():
        return override.strip().rstrip("/")
    return api_base_url.rstrip("/")


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
    _explicit_output: bool = field(default=False, repr=False)

    def log(
        self,
        output: Any = _MISSING,
        *,
        documents: Sequence[Mapping[str, Any]] | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> None:
        """Record the item's output (and optionally retrieved documents / extra context).

        An explicit ``log(output)`` wins over values captured from ``aiobs.set_output``.
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

    def _comparison_by_name(self) -> dict[str, MetricComparisonResponse]:
        if self.comparison is None:
            return {}
        rows: dict[str, MetricComparisonResponse] = {}
        for row in self.comparison.metrics:
            key = row.evaluator_name or row.evaluator_id or ""
            rows.setdefault(key, row)
        return rows

    def summary(self) -> str:
        """Plain-text table: one row per metric, with the baseline delta if any."""
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
        if not rows:
            return head + "\n  (no metrics scored)"
        header = ("metric", "mean", "pass_rate", "vs baseline" if compared else "")
        widths = [max(len(r[i]) for r in [header, *rows]) for i in range(4)]
        lines = [head]
        for row in [header, *rows]:
            lines.append("  " + "  ".join(c.ljust(w) for c, w in zip(row, widths, strict=True)))
        return "\n".join(line.rstrip() for line in lines)

    def __str__(self) -> str:
        return self.summary()


def _fmt(value: float | None) -> str:
    return "-" if value is None else f"{value:.3f}"


def _fmt_delta(row: MetricComparisonResponse | None) -> str:
    if row is None or row.delta is None:
        return ""
    return f"{row.delta:+.3f} {row.status or ''}".rstrip()


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
        url = f"{ui_base_url(self._client.base_url)}/experiments/{self.id}"
        if self.experiment.project_id:
            url += f"?project={self.experiment.project_id}"
        return url

    @property
    def params(self) -> dict[str, Any]:
        """Stored model config: ``params``, or the app config snapshot when one was bound."""
        return dict(self.experiment.experiment_model_config)

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
                    if output is not None or not run.has_output:
                        run.log(output)
            except Exception as exc:
                if raise_on_error:
                    raise
                logger.warning("aiobs: task failed on item %s: %s", item.id, exc)

        if max_concurrency == 1:
            for item in self._items:
                work(item)
            return
        with ThreadPoolExecutor(max_workers=max_concurrency) as pool:
            for future in [pool.submit(work, item) for item in self._items]:
                future.result()

    def __enter__(self) -> Experiment:
        return self

    def __exit__(self, exc_type: type[BaseException] | None, *_exc: object) -> None:
        if exc_type is not None:
            _otel.flush()
            logger.warning("aiobs experiment %s aborted; skipping scoring", self.id)
            return
        if self.result is None:
            self.finish()

    @contextmanager
    def run(self, item: DatasetItemResponse | str) -> Iterator[ItemRun]:
        """Run one item: opens a root span bound to (experiment, item) and records output.

        Inside the block call ``run.log(output)`` or ``aiobs.set_output(...)``;
        ``aiobs.set_retrieval_documents`` is captured too.
        """
        resolved = self._resolve_item(item)
        record = ItemRun(item=resolved)
        tracer = otel_trace.get_tracer("aiobs")
        token = ACTIVE_RUN.set(record)
        started = time.perf_counter()
        try:
            with tracer.start_as_current_span(
                f"aiobs.eval {self.name}", record_exception=False, set_status_on_exception=False
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
                    "aiobs local metric %s failed on item %s: %s", name, record.item.id, exc
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
                        result["metadata"] = _jsonable(score.metadata)
                results.append(result)
            entry: dict[str, Any] = {"name": name, "results": results}
            if metric.threshold is not None:
                entry["threshold"] = metric.threshold
            if metric.config:
                entry["config"] = _jsonable(dict(metric.config))
            payload.append(entry)
        try:
            self._client.experiments.submit_client_results(self.id, payload)
        except AiobsAPIError as exc:
            logger.warning(
                "aiobs: could not submit local metrics for experiment %s: %s", self.id, exc
            )
            return False
        return True

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
        for start in range(0, len(payload), _UPSERT_CHUNK):
            self._client.experiments.upsert_outputs(self.id, payload[start : start + _UPSERT_CHUNK])

        # After the outputs: client runs record the inputs fingerprint they scored.
        submitted = self._submit_local_scores(records)

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
        if evaluation is not None or submitted:
            server_summary = self._client.experiments.summary(self.id)
            if self.baseline_id is not None:
                try:
                    comparison = self._client.experiments.compare(self.id, self.baseline_id)
                except AiobsAPIError as exc:
                    logger.warning(
                        "aiobs: compare with baseline %s failed: %s", self.baseline_id, exc
                    )

        self.result = ExperimentResult(
            experiment=evaluation.experiment if evaluation else self.experiment,
            url=self.url,
            items=records,
            evaluation=evaluation,
            server_summary=server_summary,
            comparison=comparison,
            baseline_id=self.baseline_id,
        )
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
                    "aiobs: %d/%d traces not bound to experiment %s after %.0fs; "
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

DatasetLike = str | DatasetResponse | Sequence[Mapping[str, Any]] | Any
"""Dataset name, dataset id, ``DatasetResponse``, list of dicts or pandas DataFrame."""


def _resolve_project(project: str | None) -> str:
    if project is None:
        return _config.resolve_project_id()
    if _is_uuid(project):
        return project
    return set_project(project).id


def _records_from(dataset: Any) -> list[dict[str, Any]] | None:
    if hasattr(dataset, "to_json") and hasattr(dataset, "columns"):  # pandas DataFrame
        records = json.loads(dataset.to_json(orient="records", date_format="iso"))
        return [dict(r) for r in records]
    if isinstance(dataset, Sequence) and not isinstance(dataset, str | bytes):
        if not all(isinstance(row, Mapping) for row in dataset):
            raise TypeError("dataset list must contain dicts")
        return [_jsonable(dict(row)) for row in dataset]
    return None


def _item_body(row: dict[str, Any], index: int) -> dict[str, Any]:
    if "input" not in row:
        raise ValueError(f"dataset row {index} needs an 'input' key: {sorted(row)}")
    body = {k: row[k] for k in _ITEM_KEYS if row.get(k) is not None}
    extras = {k: v for k, v in row.items() if k not in _ITEM_KEYS}
    if extras:
        body["metadata"] = {**extras, **dict(body.get("metadata") or {})}
    return body


def _resolve_dataset(
    client: Client, project_id: str, dataset: DatasetLike, *, task_type: str
) -> str:
    if isinstance(dataset, DatasetResponse):
        return dataset.id
    if isinstance(dataset, str):
        if _is_uuid(dataset):
            return dataset
        matches = [d for d in client.datasets.list(project_id) if d.name == dataset]
        if not matches:
            raise ValueError(f"no dataset named {dataset!r} in project {project_id}")
        return max(matches, key=lambda d: d.version).id

    records = _records_from(dataset)
    if records is None:
        raise TypeError(
            "dataset must be a name, id, DatasetResponse, list of dicts or DataFrame; "
            f"got {type(dataset).__name__}"
        )
    if not records:
        raise ValueError("dataset is empty")
    bodies = [_item_body(row, i) for i, row in enumerate(records)]
    # Content-addressed name: re-running on the same rows reuses the dataset, so runs
    # stay comparable against each other.
    name = f"inline-{_digest([task_type, bodies])[:12]}"
    for existing in client.datasets.list(project_id):
        if existing.name == name:
            return existing.id
    created = client.datasets.create_with_items(
        project_id,
        name=name,
        items=bodies,
        task_type=task_type,
        description="Created by aiobs.evaluate() from in-memory rows",
    )
    logger.info("aiobs created dataset %s (%d items)", name, len(bodies))
    return created.id


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
            description="Created by aiobs.evaluate()",
        )
    except AiobsAPIError as exc:
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
    client = client or get_client()
    project_id = _resolve_project(project)
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
    logger.info("aiobs experiment %s started: %s", experiment.name, exp.url)
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
    ``aiobs.set_retrieval_documents`` inside it feed retrieval metrics. A task that
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
    logger.info("aiobs experiment %s finished: %s", result.experiment.name, result.url)
    return result


__all__ = [
    "Experiment",
    "ExperimentResult",
    "ItemRun",
    "LocalMetric",
    "Metric",
    "evaluate",
    "start_experiment",
]
