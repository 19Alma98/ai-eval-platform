from __future__ import annotations

import atexit
import logging
import os
import threading
import time
from collections.abc import Sequence
from typing import Literal

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.util._once import Once

from aiobs import _live, _production
from aiobs._config import project_headers, resolve_config
from aiobs.instrumentation import activate_instrumentors

logger = logging.getLogger("aiobs")

# Logger used by the OTLP HTTP exporter for retry/failure messages.
_OTLP_LOGGER_NAME = "opentelemetry.exporter.otlp.proto.http.trace_exporter"
_TRUTHY = frozenset({"1", "true", "yes", "on"})

EXPORT_TIMEOUT_S = 5.0
# After a failed export, drop batches without touching the network for this long.
FAILURE_COOLDOWN_S = 30.0
# Per-stage cap for span flush at exit (shares EXIT_FLUSH_TIMEOUT_S with metrics/scores).
EXIT_FLUSH_TIMEOUT_MS = 2000

_PROVIDER: TracerProvider | None = None
_EXPORTER: _SafeSpanExporter | None = None
_INITIALIZED: bool = False
_ATEXIT_REGISTERED: bool = False


def is_disabled() -> bool:
    """True when ``AIOBS_DISABLED`` is set to a truthy value (1/true/yes/on)."""
    return os.getenv("AIOBS_DISABLED", "").strip().lower() in _TRUTHY


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
        try:
            result = self._inner.export(spans)
        except Exception:  # noqa: BLE001 — export must never raise into the app
            logger.debug("aiobs: span export raised", exc_info=True)
            result = SpanExportResult.FAILURE
        if result is SpanExportResult.SUCCESS:
            self._on_success()
        else:
            self._on_failure(len(spans))
        return result

    def _drop(self, count: int) -> None:
        with self._lock:
            self.dropped_spans += count

    def _on_success(self) -> None:
        with self._lock:
            recovered = self._failing
            self._failing = False
            self._retry_after = 0.0
        if recovered:
            logger.info("aiobs: platform reachable again; span export resumed")

    def _on_failure(self, count: int) -> None:
        with self._lock:
            first = not self._failing
            self._failing = True
            self._retry_after = time.monotonic() + self._cooldown_s
            self.dropped_spans += count
        if first:
            logger.warning(
                "aiobs: could not export spans to the platform; dropping them "
                "(retrying in %.0fs, further failures are logged at DEBUG)",
                self._cooldown_s,
            )
        else:
            logger.debug("aiobs: dropped %d spans (platform unreachable)", count)

    def close(self) -> None:
        """Drop anything exported from now on and abort in-flight retries."""
        self._closed = True
        try:
            self._inner.shutdown()
        except Exception:  # noqa: BLE001
            logger.debug("aiobs: exporter shutdown raised", exc_info=True)

    def shutdown(self) -> None:
        if not self._closed:
            self.close()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True


def _shutdown_and_reset_global_tracer_provider() -> None:
    global _PROVIDER, _EXPORTER
    shutdown_targets: set[TracerProvider] = set()
    if _PROVIDER is not None:
        shutdown_targets.add(_PROVIDER)
    otel_tp = getattr(trace, "_TRACER_PROVIDER", None)
    if isinstance(otel_tp, TracerProvider):
        shutdown_targets.add(otel_tp)
    for provider in shutdown_targets:
        try:
            provider.shutdown()
        except Exception:  # noqa: BLE001
            logger.debug("aiobs: tracer provider shutdown raised", exc_info=True)

    _PROVIDER = None
    _EXPORTER = None
    # Private OTEL globals — used to allow force=True re-init in tests/apps.
    setattr(trace, "_TRACER_PROVIDER", None)  # noqa: B010
    setattr(trace, "_TRACER_PROVIDER_SET_ONCE", Once())  # noqa: B010


def _reset_for_tests() -> None:
    global _INITIALIZED
    _shutdown_and_reset_global_tracer_provider()
    _live._reset_for_tests()
    _INITIALIZED = False


def _at_exit() -> None:
    """Flush pending spans (bounded), then stop export so exit never hangs."""
    provider, exporter = _PROVIDER, _EXPORTER
    if provider is None:
        return
    from aiobs import _scores  # lazy: avoids an import cycle through aiobs._context

    try:
        remaining_ms = int(_scores.exit_remaining() * 1000)
        timeout_ms = min(EXIT_FLUSH_TIMEOUT_MS, remaining_ms)
        provider.force_flush(timeout_ms)
    except Exception:  # noqa: BLE001
        logger.debug("aiobs: flush at exit raised", exc_info=True)
    if exporter is not None:
        exporter.close()
    try:
        provider.shutdown()
    except Exception:  # noqa: BLE001
        logger.debug("aiobs: shutdown at exit raised", exc_info=True)


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

    ``live=True`` (or ``AIOBS_LIVE=1``) turns each outermost ``@aiobs.trace`` call
    outside an experiment into a platform live interaction; ``live_sample_rate``
    (or ``AIOBS_LIVE_SAMPLE_RATE``, default 1.0) is the fraction sent to the judge.
    ``metrics_workers`` (or ``AIOBS_METRICS_WORKERS``, default 2) is the size of the
    background pool that runs ``@aiobs.trace(metrics=...)``.
    """
    global _PROVIDER, _EXPORTER, _INITIALIZED, _ATEXIT_REGISTERED

    if is_disabled():
        logger.info("aiobs: AIOBS_DISABLED is set; tracing disabled")
        return

    if _INITIALIZED and not force:
        logger.info("aiobs already initialized; skipping (pass force=True to re-init)")
        return

    if force:
        _shutdown_and_reset_global_tracer_provider()
        _INITIALIZED = False

    try:
        _live.configure(enabled=live, sample_rate=live_sample_rate)
    except (TypeError, ValueError) as exc:
        logger.warning("aiobs: live capture disabled: %s", exc)
        _live.configure(enabled=False)

    try:
        _production.configure(workers=metrics_workers)
    except (TypeError, ValueError) as exc:
        logger.warning("aiobs: metrics_workers ignored: %s", exc)

    try:
        config = resolve_config(
            project_id=project_id,
            project_slug=project_slug,
            endpoint=endpoint,
            service_name=service_name,
        )
        headers = project_headers(config)
        resource = Resource.create({"service.name": config.service_name})
        # aiobs registers its own bounded atexit handler instead of OTEL's.
        provider = TracerProvider(resource=resource, shutdown_on_exit=False)
        exporter = _SafeSpanExporter(
            OTLPSpanExporter(endpoint=config.endpoint, headers=headers, timeout=EXPORT_TIMEOUT_S)
        )
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
    except Exception as exc:  # noqa: BLE001 — init must never break the host app
        logger.warning("aiobs: tracing disabled, init failed: %s", exc)
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
            logger.warning("aiobs: auto-instrumentation skipped: %s", exc)

    _PROVIDER = provider
    _EXPORTER = exporter
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
            logger.debug("aiobs: flush raised", exc_info=True)
            ok = False
    from aiobs import _production, _scores  # lazy: avoids an import cycle through aiobs._context

    try:
        ok = _production.drain(max(0.0, deadline - time.monotonic())) and ok
    except Exception:  # noqa: BLE001
        logger.debug("aiobs: production metrics drain raised", exc_info=True)
        ok = False
    try:
        scores_ok = _scores.flush(max(0.0, deadline - time.monotonic()))
    except Exception:  # noqa: BLE001
        logger.debug("aiobs: score flush raised", exc_info=True)
        scores_ok = False
    return scores_ok and ok
