from __future__ import annotations

import atexit
import logging
import os
import threading
import time
from collections.abc import Sequence
from typing import Literal

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http import Compression
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.util._once import Once

from opengrade import _live, _production
from opengrade._config import project_headers, resolve_config
from opengrade.instrumentation import activate_instrumentors, deactivate_instrumentors

logger = logging.getLogger("opengrade")

# Logger used by the OTLP HTTP exporter for retry/failure messages.
_OTLP_LOGGER_NAME = "opentelemetry.exporter.otlp.proto.http.trace_exporter"
_TRUTHY = frozenset({"1", "true", "yes", "on"})

EXPORT_TIMEOUT_S = 5.0
# After a failed export, drop batches without touching the network for this long.
FAILURE_COOLDOWN_S = 30.0
# Per-stage cap for span flush at exit (shares EXIT_FLUSH_TIMEOUT_S with metrics/scores).
EXIT_FLUSH_TIMEOUT_MS = 2000
# Stay under the platform's 4 MiB OTLP body limit (serialized, pre-gzip).
OTLP_MAX_REQUEST_BYTES = 2 * 1024 * 1024
OTLP_MAX_EXPORT_BATCH_SIZE = 64

_PROVIDER: TracerProvider | None = None
_PROCESSOR: BatchSpanProcessor | None = None
_EXPORTER: _SafeSpanExporter | None = None
_OWNS_PROVIDER: bool = False
_INITIALIZED: bool = False
_ATEXIT_REGISTERED: bool = False


def is_disabled() -> bool:
    """True when ``OPENGRADE_DISABLED`` is set to a truthy value (1/true/yes/on)."""
    return os.getenv("OPENGRADE_DISABLED", "").strip().lower() in _TRUTHY


class _DropOtlpExporterLogs(logging.Filter):
    """Silence the OTLP exporter's per-batch errors; ``_SafeSpanExporter`` reports instead."""

    def filter(self, record: logging.LogRecord) -> bool:
        return False


_OTLP_LOG_FILTER = _DropOtlpExporterLogs()


class _SafeSpanExporter(SpanExporter):
    """Wraps the OTLP exporter so an unreachable platform never surfaces in the app.

    Failed batches are dropped. One warning is logged when the platform becomes
    unreachable and one info when it recovers; batches arriving during the
    cooldown after a failure are dropped without a network call.
    """

    def __init__(self, inner: SpanExporter, *, cooldown_s: float = FAILURE_COOLDOWN_S) -> None:
        self._inner = inner
        self._cooldown_s = cooldown_s
        self._lock = threading.Lock()
        self._retry_after = 0.0
        self._failing = False
        self._closed = False
        self.dropped_spans = 0

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        if self._closed or time.monotonic() < self._retry_after:
            self._drop(len(spans))
            return SpanExportResult.FAILURE
        batch = list(spans)
        result = self._export_split(batch)
        if result is SpanExportResult.SUCCESS:
            self._on_success()
            return result
        # Single-span failure (often oversize): drop without silencing later batches.
        if len(batch) <= 1:
            return SpanExportResult.FAILURE
        # Whole batch failed even after bisecting → treat as connectivity outage.
        self._on_failure(0)  # leaves already counted drops
        return SpanExportResult.FAILURE

    def _export_split(self, spans: list[ReadableSpan]) -> SpanExportResult:
        try:
            result = self._inner.export(spans)
        except Exception:  # noqa: BLE001 — export must never raise into the app
            logger.debug("opengrade: span export raised", exc_info=True)
            result = SpanExportResult.FAILURE
        if result is SpanExportResult.SUCCESS:
            return SpanExportResult.SUCCESS
        if len(spans) <= 1:
            self._drop(len(spans))
            logger.debug("opengrade: dropped %d oversize or rejected span(s)", len(spans))
            return SpanExportResult.FAILURE
        mid = len(spans) // 2
        left = self._export_split(spans[:mid])
        right = self._export_split(spans[mid:])
        if left is SpanExportResult.SUCCESS or right is SpanExportResult.SUCCESS:
            return SpanExportResult.SUCCESS
        return SpanExportResult.FAILURE

    def _drop(self, count: int) -> None:
        with self._lock:
            self.dropped_spans += count

    def _on_success(self) -> None:
        with self._lock:
            recovered = self._failing
            self._failing = False
            self._retry_after = 0.0
        if recovered:
            logger.info("opengrade: platform reachable again; span export resumed")

    def _on_failure(self, count: int) -> None:
        with self._lock:
            first = not self._failing
            self._failing = True
            self._retry_after = time.monotonic() + self._cooldown_s
            self.dropped_spans += count
        if first:
            logger.warning(
                "opengrade: could not export spans to the platform; dropping them "
                "(retrying in %.0fs, further failures are logged at DEBUG)",
                self._cooldown_s,
            )
        else:
            logger.debug("opengrade: dropped %d spans (platform unreachable)", count)

    def close(self) -> None:
        """Drop anything exported from now on and abort in-flight retries."""
        self._closed = True
        try:
            self._inner.shutdown()
        except Exception:  # noqa: BLE001
            logger.debug("opengrade: exporter shutdown raised", exc_info=True)

    def shutdown(self) -> None:
        if not self._closed:
            self.close()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True


def _teardown_opengrade_tracing(*, reset_global: bool) -> None:
    """Stop opengrade export. Only shut down / clear the global provider when we own it."""
    global _PROVIDER, _PROCESSOR, _EXPORTER, _OWNS_PROVIDER
    processor, exporter, provider, owns = _PROCESSOR, _EXPORTER, _PROVIDER, _OWNS_PROVIDER
    _PROCESSOR = None
    _EXPORTER = None
    _PROVIDER = None
    _OWNS_PROVIDER = False

    if exporter is not None:
        exporter.close()
    if processor is not None:
        try:
            processor.shutdown()  # type: ignore[no-untyped-call]
        except Exception:  # noqa: BLE001
            logger.debug("opengrade: span processor shutdown raised", exc_info=True)

    if reset_global and owns and provider is not None:
        try:
            provider.shutdown()
        except Exception:  # noqa: BLE001
            logger.debug("opengrade: tracer provider shutdown raised", exc_info=True)
        # Private OTEL globals — only when opengrade installed the global provider.
        setattr(trace, "_TRACER_PROVIDER", None)  # noqa: B010
        setattr(trace, "_TRACER_PROVIDER_SET_ONCE", Once())  # noqa: B010


def _shutdown_and_reset_global_tracer_provider() -> None:
    """Tear down opengrade tracing and clear the global provider (test / owned-init path)."""
    owns = _OWNS_PROVIDER
    _teardown_opengrade_tracing(reset_global=owns)
    if not owns:
        # Test isolation: drop whatever is on the global slot without assuming ownership.
        otel_tp = getattr(trace, "_TRACER_PROVIDER", None)
        if isinstance(otel_tp, TracerProvider):
            try:
                otel_tp.shutdown()
            except Exception:  # noqa: BLE001
                logger.debug("opengrade: tracer provider shutdown raised", exc_info=True)
        setattr(trace, "_TRACER_PROVIDER", None)  # noqa: B010
        setattr(trace, "_TRACER_PROVIDER_SET_ONCE", Once())  # noqa: B010


def _reset_for_tests() -> None:
    global _INITIALIZED
    deactivate_instrumentors()
    _shutdown_and_reset_global_tracer_provider()
    _live._reset_for_tests()
    _INITIALIZED = False


def _at_exit() -> None:
    """Flush pending spans (bounded), then stop opengrade export so exit never hangs."""
    provider = _PROVIDER
    if provider is None:
        return
    from opengrade import _scores  # lazy: avoids an import cycle through opengrade._context

    try:
        remaining_ms = int(_scores.exit_remaining() * 1000)
        timeout_ms = min(EXIT_FLUSH_TIMEOUT_MS, remaining_ms)
        provider.force_flush(timeout_ms)
    except Exception:  # noqa: BLE001
        logger.debug("opengrade: flush at exit raised", exc_info=True)
    _teardown_opengrade_tracing(reset_global=_OWNS_PROVIDER)


def init(
    *,
    project_id: str | None = None,
    project_slug: str | None = None,
    endpoint: str | None = None,
    service_name: str | None = None,
    instrument: Literal["auto", False] | Sequence[str] = "auto",
    force: bool = False,
    live: bool | None = None,
    live_sample_rate: float | None = None,
    metrics_workers: int | None = None,
) -> None:
    """Configure OTLP export. Never raises: on bad config it warns and stays a no-op.

    ``live=True`` (or ``OPENGRADE_LIVE=1``) turns each outermost ``@opengrade.trace`` call
    outside an experiment into a platform live interaction; ``live_sample_rate``
    (or ``OPENGRADE_LIVE_SAMPLE_RATE``, default 1.0) is the fraction sent to the judge.
    ``metrics_workers`` (or ``OPENGRADE_METRICS_WORKERS``, default 2) is the size of the
    background pool that runs ``@opengrade.trace(metrics=...)``.
    """
    global _PROVIDER, _PROCESSOR, _EXPORTER, _OWNS_PROVIDER, _INITIALIZED, _ATEXIT_REGISTERED

    if is_disabled():
        logger.info("opengrade: OPENGRADE_DISABLED is set; tracing disabled")
        return

    if _INITIALIZED and not force:
        logger.info("opengrade already initialized; skipping (pass force=True to re-init)")
        return

    if force:
        # OpenInference instrumentors are process singletons; uninstrument before
        # tearing down the provider so they do not keep exporting to a dead one.
        deactivate_instrumentors()
        # Never shut down a host TracerProvider we did not create.
        _teardown_opengrade_tracing(reset_global=_OWNS_PROVIDER)
        _INITIALIZED = False

    try:
        _live.configure(enabled=live, sample_rate=live_sample_rate)
    except (TypeError, ValueError) as exc:
        logger.warning("opengrade: live capture disabled: %s", exc)
        _live.configure(enabled=False)

    try:
        _production.configure(workers=metrics_workers)
    except (TypeError, ValueError) as exc:
        logger.warning("opengrade: metrics_workers ignored: %s", exc)

    try:
        config = resolve_config(
            project_id=project_id,
            project_slug=project_slug,
            endpoint=endpoint,
            service_name=service_name,
        )
        headers = project_headers(config)
        resource = Resource.create({"service.name": config.service_name})
        exporter = _SafeSpanExporter(
            OTLPSpanExporter(
                endpoint=config.endpoint,
                headers=headers,
                timeout=EXPORT_TIMEOUT_S,
                compression=Compression.Gzip,
                max_request_size=OTLP_MAX_REQUEST_BYTES,
            )
        )
        processor = BatchSpanProcessor(exporter, max_export_batch_size=OTLP_MAX_EXPORT_BATCH_SIZE)
        existing = trace.get_tracer_provider()
        if isinstance(existing, TracerProvider):
            # Host already has OTel (Datadog, Honeycomb, …): attach, do not replace.
            existing.add_span_processor(processor)
            provider = existing
            owns_provider = False
        else:
            # opengrade registers its own bounded atexit handler instead of OTEL's.
            provider = TracerProvider(resource=resource, shutdown_on_exit=False)
            provider.add_span_processor(processor)
            trace.set_tracer_provider(provider)
            owns_provider = True
    except Exception as exc:  # noqa: BLE001 — init must never break the host app
        logger.warning("opengrade: tracing disabled, init failed: %s", exc)
        return

    otlp_logger = logging.getLogger(_OTLP_LOGGER_NAME)
    if _OTLP_LOG_FILTER not in otlp_logger.filters:
        otlp_logger.addFilter(_OTLP_LOG_FILTER)

    if instrument is not False:
        keys: Sequence[str] | None
        if instrument == "auto":
            keys = None  # means all registered
        else:
            keys = list(instrument)
        try:
            activate_instrumentors(keys, provider)
        except Exception as exc:  # noqa: BLE001
            logger.warning("opengrade: auto-instrumentation skipped: %s", exc)

    # Record the active project for control-plane calls (log_score, metrics, …).
    from opengrade._config import _set_active_project

    if config.project_id:
        _set_active_project(project_id=config.project_id)
    elif config.project_slug:
        _set_active_project(project_slug=config.project_slug)

    _PROVIDER = provider
    _PROCESSOR = processor
    _EXPORTER = exporter
    _OWNS_PROVIDER = owns_provider
    _INITIALIZED = True
    if not _ATEXIT_REGISTERED:
        atexit.register(_at_exit)
        _ATEXIT_REGISTERED = True


def flush(timeout_millis: int = 5000) -> bool:
    """Flush spans, then production metrics, then queued trace scores.

    ``timeout_millis`` is the total budget: each stage gets what the previous left.
    Metrics are drained before scores are flushed because they produce scores.
    """
    deadline = time.monotonic() + timeout_millis / 1000
    ok = True
    if _PROVIDER is not None:
        try:
            ok = bool(_PROVIDER.force_flush(timeout_millis))
        except Exception:  # noqa: BLE001
            logger.debug("opengrade: flush raised", exc_info=True)
            ok = False
    from opengrade import (
        _production,
        _scores,
    )  # lazy: avoids an import cycle through opengrade._context

    try:
        ok = _production.drain(max(0.0, deadline - time.monotonic())) and ok
    except Exception:  # noqa: BLE001
        logger.debug("opengrade: production metrics drain raised", exc_info=True)
        ok = False
    try:
        scores_ok = _scores.flush(max(0.0, deadline - time.monotonic()))
    except Exception:  # noqa: BLE001
        logger.debug("opengrade: score flush raised", exc_info=True)
        scores_ok = False
    return scores_ok and ok
