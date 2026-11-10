from __future__ import annotations

import inspect
import logging
import math
import numbers
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from contextvars import ContextVar, Token, copy_context
from dataclasses import dataclass, field
from typing import Any

from opentelemetry import trace as otel_trace
from opentelemetry.trace import Status, StatusCode

from opengrade import _otel
from opengrade._async import run_sync
from opengrade._eval_run import bind_evaluation
from opengrade._http import OpengradeAPIError, OpengradeError
from opengrade._links import experiment_item_url, experiment_url, trace_url, ui_base_url
from opengrade._opengrade import current
from opengrade._run_context import ACTIVE_RUN
from opengrade._trace import current_trace_id, truncate_value
from opengrade.client import Client
from opengrade.experiment.result import (
    ExperimentResult,
    announce,
)
from opengrade.experiment.serialization import (
    _UPSERT_CHUNK,
    _UPSERT_MAX_BYTES,
    _chunk_by_bytes,
    _jsonable,
)
from opengrade.experiment.setup import (
    _MISSING,
    MAX_REPEATS,
    TASK_FAILED_EXPLANATION,
    _local_name,
)
from opengrade.metrics import LocalMetric, Sample, Score, evaluate_metric
from opengrade.models import (
    DatasetItemResponse,
    EvaluateResponse,
    ExperimentCompareResponse,
    ExperimentItemOutputResponse,
    ExperimentResponse,
    ExperimentSummaryResponse,
)

logger = logging.getLogger("opengrade")

ACTIVE_EXPERIMENT: ContextVar[Experiment | None] = ContextVar(
    "opengrade_active_experiment", default=None
)


@dataclass
class ItemRun:
    """One dataset item executed inside ``Experiment.run()``."""

    item: DatasetItemResponse
    repeat: int = 0
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

    def _capture_search_query(self, query: str) -> None:
        self.context["search_query"] = query


@dataclass
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
        repeats: int = 1,
        group_by: str | None = None,
    ) -> None:
        if not 1 <= repeats <= MAX_REPEATS:
            raise ValueError(f"repeats must be between 1 and {MAX_REPEATS}")
        self.repeats = repeats
        self.group_by = group_by
        self._client = client
        self.experiment = experiment
        self._items = items
        self._items_by_id = {item.id: item for item in items}
        self._metrics_set_id = metrics_set_id
        self._score_on_server = score_on_server
        self._local_metrics = local_metrics
        self.baseline_id = baseline_id
        self._records: dict[tuple[str, int], ItemRun] = {}
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
        """Run ``task(item)`` on every item inside ``run(item)``, logging its return value.

        With ``repeats`` > 1 every item runs that many times (one trace and output each).
        """
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be >= 1")

        def work(item: DatasetItemResponse, repeat: int) -> None:
            try:
                with self.run(item, repeat=repeat) as run:
                    output = task(item)
                    if inspect.isawaitable(output):
                        output = run_sync(output)
                    if output is not None or not run.has_output:
                        run.log(output)
            except Exception as exc:
                if raise_on_error:
                    raise
                logger.warning("opengrade: task failed on item %s: %s", item.id, exc)

        jobs = [(item, repeat) for item in self._items for repeat in range(self.repeats)]
        if max_concurrency == 1:
            for item, repeat in jobs:
                work(item, repeat)
            return
        with ThreadPoolExecutor(max_workers=max_concurrency) as pool:
            futures = [pool.submit(copy_context().run, work, item, repeat) for item, repeat in jobs]
            for future in futures:
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
    def run(self, item: DatasetItemResponse | str, *, repeat: int = 0) -> Iterator[ItemRun]:
        """Run one item: opens a root span bound to (experiment, item) and records output.

        Inside the block call ``run.log(output)`` or ``opengrade.set_output(...)``;
        ``opengrade.set_retrieval_documents`` is captured too. ``repeat`` (0-based) tells
        repeated runs of the same item apart; running the same pair again replaces it.
        """
        resolved = self._resolve_item(item)
        if not 0 <= repeat < MAX_REPEATS:
            raise ValueError(f"repeat must be between 0 and {MAX_REPEATS - 1}")
        record = ItemRun(item=resolved, repeat=repeat)
        tracer = otel_trace.get_tracer("opengrade")
        token = ACTIVE_RUN.set(record)
        experiment_token = ACTIVE_EXPERIMENT.set(self)
        started = time.perf_counter()
        try:
            with tracer.start_as_current_span(
                f"opengrade.eval {self.name}", record_exception=False, set_status_on_exception=False
            ) as span:
                span.set_attribute("openinference.span.kind", "CHAIN")
                bind_evaluation(experiment_id=self.id, dataset_item_id=resolved.id, repeat=repeat)
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
                self._records[(resolved.id, repeat)] = record

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
                if record.repeat:
                    result["repeat"] = record.repeat
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
        payload = [
            _output_entry(record, stored.get((record.item.id, record.repeat))) for record in records
        ]
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
            server_summary = self._summary_with_groups()
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
                comparison = self._client.experiments.compare(
                    self.id, self.baseline_id, group_by=self.group_by
                )
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

    def _summary_with_groups(self) -> ExperimentSummaryResponse:
        if self.group_by is None:
            return self._client.experiments.summary(self.id)
        try:
            return self._client.experiments.summary(self.id, group_by=self.group_by)
        except OpengradeAPIError as exc:
            if exc.status != 400:
                raise
            # A bad group key must not lose the run's scores.
            logger.warning("opengrade: group_by %r rejected: %s", self.group_by, exc)
            return self._client.experiments.summary(self.id)

    def _await_trace_binding(
        self, records: list[ItemRun], bind_timeout: float, poll_interval: float
    ) -> dict[tuple[str, int], ExperimentItemOutputResponse]:
        """Wait until OTLP-ingested traces are bound, so our PUT lands last."""
        traced = {(r.item.id, r.repeat): r.trace_id for r in records if r.trace_id}
        if traced and current().tracing_enabled:
            _otel.flush()
        else:
            traced = {}
        deadline = time.monotonic() + bind_timeout
        while True:
            stored = {
                (str(o.dataset_item_id), o.repeat): o
                for o in self._client.experiments.list_outputs(self.id)
            }
            pending = [
                key
                for key, trace_id in traced.items()
                if (o := stored.get(key)) is None or o.metadata.get("source_trace_id") != trace_id
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
    if record.repeat:
        entry["repeat"] = record.repeat
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
