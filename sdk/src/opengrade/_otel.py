from __future__ import annotations

import atexit
import logging
import os
import sys
import threading
import time
import weakref
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Literal, cast

if TYPE_CHECKING:
    from opengrade._opengrade import Opengrade

from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.sdk.trace import ReadableSpan, Span, SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.util._once import Once

from opengrade import _live, _production, _state
from opengrade._config import (
    auth_headers,
    configure_capture,
    project_headers,
    resolve_config,
)
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

_OTEL_MODULE_STATE_KEYS = (
    "_PROVIDER",
    "_PROCESSOR",
    "_EXPORTER",
    "_OWNS_PROVIDER",
    "_INITIALIZED",
    "_ATEXIT_REGISTERED",
)

_INSTANCE_ATTR = "opengrade.instance"
_INSTANCE_ID_COUNTER = 0
_INSTANCE_ID_LOCK = threading.Lock()
_SHARED_PROVIDER: TracerProvider | None = None
_OWNS_SHARED_PROVIDER = False
_ROUTER: _RoutingSpanProcessor | None = None
_OPEN_TRACING_INSTANCES: weakref.WeakSet[Opengrade] = weakref.WeakSet()
_INSTRUMENTOR_OWNER: weakref.ReferenceType[Opengrade] | None = None


def _next_instance_id() -> int:
    global _INSTANCE_ID_COUNTER
    with _INSTANCE_ID_LOCK:
        _INSTANCE_ID_COUNTER += 1
        return _INSTANCE_ID_COUNTER


def _clear_module_state_keys() -> None:
    """Drop pytest shadow attrs; avoids stale ``None`` after monkeypatch on PEP 562 modules."""
    mod = sys.modules[__name__]
    for key in _OTEL_MODULE_STATE_KEYS:
        mod.__dict__.pop(key, None)


def _current_provider() -> TracerProvider | None:
    mod = sys.modules[__name__]
    if "_PROVIDER" in mod.__dict__:
        return cast(TracerProvider | None, mod.__dict__["_PROVIDER"])
    if _SHARED_PROVIDER is not None:
        return _SHARED_PROVIDER
    return _state._default().provider


def _atexit_registered() -> bool:
    mod = sys.modules[__name__]
    if "_ATEXIT_REGISTERED" in mod.__dict__:
        return cast(bool, mod.__dict__["_ATEXIT_REGISTERED"])
    return _state._default().otel_atexit_registered


def _mark_atexit_registered() -> None:
    mod = sys.modules[__name__]
    if "_ATEXIT_REGISTERED" in mod.__dict__:
        mod.__dict__["_ATEXIT_REGISTERED"] = True
    else:
        _state._default().otel_atexit_registered = True


def is_disabled() -> bool:
    """True when ``OPENGRADE_DISABLED`` is set to a truthy value (1/true/yes/on)."""
    return os.getenv("OPENGRADE_DISABLED", "").strip().lower() in _TRUTHY


class _DropOtlpExporterLogs(logging.Filter):
    """Silence the OTLP exporter's per-batch errors; ``_SafeSpanExporter`` reports instead."""

    def filter(self, record: logging.LogRecord) -> bool:
        return False


_OTLP_LOG_FILTER = _DropOtlpExporterLogs()


class _SpanWithoutInstanceAttr:
    """``ReadableSpan`` view that omits the internal routing attribute."""

    __slots__ = ("_span", "_attributes")

    def __init__(self, span: ReadableSpan) -> None:
        self._span = span
        attrs = span.attributes
        if attrs and _INSTANCE_ATTR in attrs:
            attributes: Any = {k: v for k, v in attrs.items() if k != _INSTANCE_ATTR}
        else:
            attributes = attrs
        self._attributes = attributes

    def __getattr__(self, name: str) -> Any:
        return getattr(self._span, name)

    @property
    def attributes(self) -> Any:
        return self._attributes


class _RoutingSpanProcessor(SpanProcessor):
    """Routes ended spans to the per-instance ``BatchSpanProcessor``."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._processors: dict[int, SpanProcessor] = {}
        self._release_attrs: dict[int, dict[str, str]] = {}

    def register(self, instance_id: int, processor: SpanProcessor) -> None:
        with self._lock:
            self._processors[instance_id] = processor

    def register_release_attrs(self, instance_id: int, attributes: dict[str, str]) -> None:
        with self._lock:
            self._release_attrs[instance_id] = attributes

    def unregister(self, instance_id: int) -> None:
        with self._lock:
            self._processors.pop(instance_id, None)
            self._release_attrs.pop(instance_id, None)

    def on_start(self, span: Span, parent_context: Context | None = None) -> None:
        try:
            from opengrade._opengrade import current

            og = current()
            if og.tracing_enabled:
                span.set_attribute(_INSTANCE_ATTR, og._instance_id)
                with self._lock:
                    release = self._release_attrs.get(og._instance_id)
                if release:
                    span.set_attributes(release)
        except Exception:  # noqa: BLE001
            logger.debug("opengrade: routing on_start failed", exc_info=True)

    def on_end(self, span: ReadableSpan) -> None:
        attrs = span.attributes
        raw = attrs.get(_INSTANCE_ATTR) if attrs else None
        if raw is None:
            return
        try:
            instance_id = int(raw)
        except (TypeError, ValueError):
            return
        with self._lock:
            processor = self._processors.get(instance_id)
        if processor is None:
            return
        processor.on_end(_SpanWithoutInstanceAttr(span))

    def shutdown(self) -> None:
        with self._lock:
            processors = list(self._processors.values())
        for processor in processors:
            try:
                processor.shutdown()
            except Exception:  # noqa: BLE001
                logger.debug("opengrade: routed processor shutdown raised", exc_info=True)

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        with self._lock:
            processors = list(self._processors.values())
        ok = True
        for processor in processors:
            try:
                ok = bool(processor.force_flush(timeout_millis)) and ok
            except Exception:  # noqa: BLE001
                logger.debug("opengrade: routed processor flush raised", exc_info=True)
                ok = False
        return ok


def _get_or_create_router() -> _RoutingSpanProcessor:
    global _ROUTER
    if _ROUTER is None:
        _ROUTER = _RoutingSpanProcessor()
    return _ROUTER


def _provider_has_router(provider: TracerProvider, router: _RoutingSpanProcessor) -> bool:
    # SDK stores processors on the provider; tolerate missing attr in stubs.
    processors = getattr(provider, "_span_processors", None)
    if processors is None:
        return False
    return router in processors


# HTTP statuses where splitting the batch may salvage part of it (body too large /
# per-item validation). 5xx and connection failures must not bisect.
_SIZE_RELATED_STATUS = frozenset({400, 413})


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
        self._last_status: int | None = None
        self._http_attempted = False
        self._install_status_probe()

    def _install_status_probe(self) -> None:
        """Record HTTP status from the OTLP client's export result when available."""
        client = getattr(self._inner, "_client", None)
        if client is None or getattr(client, "_opengrade_status_probed", False):
            return
        original = client.export

        def probed(data: bytes, *args: Any, **kwargs: Any) -> Any:
            self._http_attempted = True
            outcome = original(data, *args, **kwargs)
            self._last_status = getattr(outcome, "status_code", None)
            return outcome

        client.export = probed
        client._opengrade_status_probed = True

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        if self._closed or time.monotonic() < self._retry_after:
            self._drop(len(spans))
            return SpanExportResult.FAILURE
        batch = list(spans)
        deadline = time.monotonic() + EXPORT_TIMEOUT_S
        result = self._export_split(batch, deadline)
        if result is SpanExportResult.SUCCESS:
            self._on_success()
            return result
        # Single-span failure (often oversize): drop without silencing later batches.
        if len(batch) <= 1:
            return SpanExportResult.FAILURE
        # Whole batch failed (outage, or size-split exhausted) → cooldown.
        self._on_failure(0)  # leaves already counted drops
        return SpanExportResult.FAILURE

    def _failure_is_size_related(self) -> bool:
        status = self._last_status
        if status is None:
            status = getattr(self._inner, "last_export_status", None)
        if status in _SIZE_RELATED_STATUS:
            return True
        # Client-side max_request_size rejection: FAILURE with no HTTP round-trip.
        if (
            status is None
            and not self._http_attempted
            and getattr(self._inner, "_client", None) is not None
        ):
            return True
        return False

    def _export_once(self, spans: list[ReadableSpan]) -> tuple[SpanExportResult, bool]:
        self._last_status = None
        self._http_attempted = False
        try:
            result = self._inner.export(spans)
        except Exception:  # noqa: BLE001 — export must never raise into the app
            logger.debug("opengrade: span export raised", exc_info=True)
            return SpanExportResult.FAILURE, False
        if result is SpanExportResult.SUCCESS:
            return result, False
        return result, self._failure_is_size_related()

    def _export_split(self, spans: list[ReadableSpan], deadline: float) -> SpanExportResult:
        if self._closed or time.monotonic() >= deadline:
            self._drop(len(spans))
            return SpanExportResult.FAILURE
        result, size_related = self._export_once(spans)
        if result is SpanExportResult.SUCCESS:
            return SpanExportResult.SUCCESS
        if len(spans) <= 1:
            self._drop(len(spans))
            logger.debug("opengrade: dropped %d oversize or rejected span(s)", len(spans))
            return SpanExportResult.FAILURE
        if not size_related:
            # 5xx / connection / other: one attempt, then cooldown in export().
            self._drop(len(spans))
            return SpanExportResult.FAILURE
        mid = len(spans) // 2
        left = self._export_split(spans[:mid], deadline)
        right = self._export_split(spans[mid:], deadline)
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


def _teardown_instance_tracing(og: Opengrade) -> None:
    """Stop OTLP export for a single ``Opengrade`` instance."""
    global _INSTRUMENTOR_OWNER

    rt = og._runtime
    processor, exporter = rt.processor, rt.exporter
    rt.processor = None
    rt.exporter = None
    rt.provider = None
    rt.initialized = False
    og.tracing_enabled = False

    router = _ROUTER
    if router is not None:
        router.unregister(og._instance_id)

    if exporter is not None:
        close = getattr(exporter, "close", None)
        if callable(close):
            close()
        else:
            exporter.shutdown()
    if processor is not None:
        try:
            processor.shutdown()
        except Exception:  # noqa: BLE001
            logger.debug("opengrade: span processor shutdown raised", exc_info=True)

    _OPEN_TRACING_INSTANCES.discard(og)
    owner = _INSTRUMENTOR_OWNER() if _INSTRUMENTOR_OWNER is not None else None
    if owner is og:
        deactivate_instrumentors()
        _INSTRUMENTOR_OWNER = None


def _all_tracing_instances() -> list[Opengrade]:
    from opengrade._opengrade import _default_opengrade

    seen: set[int] = set()
    ordered: list[Opengrade] = []
    for og in list(_OPEN_TRACING_INSTANCES):
        if id(og) not in seen:
            seen.add(id(og))
            ordered.append(og)
    default = _default_opengrade()
    if default._runtime.initialized and id(default) not in seen:
        ordered.append(default)
    return ordered


def _teardown_opengrade_tracing(*, reset_global: bool) -> None:
    """Stop opengrade export for every initialized instance."""
    global _SHARED_PROVIDER, _OWNS_SHARED_PROVIDER, _ROUTER

    owns = _OWNS_SHARED_PROVIDER
    for og in _all_tracing_instances():
        _teardown_instance_tracing(og)

    if reset_global and owns and _SHARED_PROVIDER is not None:
        try:
            _SHARED_PROVIDER.shutdown()
        except Exception:  # noqa: BLE001
            logger.debug("opengrade: tracer provider shutdown raised", exc_info=True)
        setattr(trace, "_TRACER_PROVIDER", None)  # noqa: B010
        setattr(trace, "_TRACER_PROVIDER_SET_ONCE", Once())  # noqa: B010

    _SHARED_PROVIDER = None
    _OWNS_SHARED_PROVIDER = False
    _ROUTER = None
    rt = _state._default()
    rt.processor = None
    rt.exporter = None
    rt.provider = None
    rt.owns_provider = False
    rt.initialized = False


def _shutdown_and_reset_global_tracer_provider() -> None:
    """Tear down opengrade tracing and clear the global provider (test / owned-init path)."""
    owns = _OWNS_SHARED_PROVIDER
    _teardown_opengrade_tracing(reset_global=owns)
    if not owns:
        otel_tp = getattr(trace, "_TRACER_PROVIDER", None)
        if isinstance(otel_tp, TracerProvider):
            try:
                otel_tp.shutdown()
            except Exception:  # noqa: BLE001
                logger.debug("opengrade: tracer provider shutdown raised", exc_info=True)
        setattr(trace, "_TRACER_PROVIDER", None)  # noqa: B010
        setattr(trace, "_TRACER_PROVIDER_SET_ONCE", Once())  # noqa: B010


def _parse_trace_sample_rate(value: object) -> float:
    rate = float(value)  # type: ignore[arg-type]
    if not 0.0 <= rate <= 1.0:
        raise ValueError(f"trace_sample_rate must be within [0, 1], got {rate}")
    return rate


def resolve_trace_sample_rate(explicit: float | None = None) -> float:
    """``init(trace_sample_rate=...)`` > ``OPENGRADE_TRACE_SAMPLE_RATE`` > 1.0."""
    if explicit is not None:
        return _parse_trace_sample_rate(explicit)
    raw = os.getenv("OPENGRADE_TRACE_SAMPLE_RATE", "").strip()
    if not raw:
        return 1.0
    try:
        return _parse_trace_sample_rate(raw)
    except (TypeError, ValueError):
        logger.warning("opengrade: invalid OPENGRADE_TRACE_SAMPLE_RATE=%r; keeping all traces", raw)
        return 1.0


def _reset_for_tests() -> None:
    global _INSTANCE_ID_COUNTER
    _clear_module_state_keys()
    deactivate_instrumentors()
    _shutdown_and_reset_global_tracer_provider()
    _live._reset_for_tests()
    configure_capture()
    _state._default().initialized = False
    _INSTANCE_ID_COUNTER = 0
    from opengrade._opengrade import _reset_opengrade_for_tests

    _reset_opengrade_for_tests()


def _at_exit() -> None:
    """Flush pending spans (bounded), then stop opengrade export so exit never hangs."""
    global _SHARED_PROVIDER, _ROUTER

    provider = _current_provider()
    if provider is None:
        return
    from opengrade import _scores  # lazy: avoids an import cycle through opengrade._context

    try:
        remaining_ms = int(_scores.exit_remaining() * 1000)
        timeout_ms = min(EXIT_FLUSH_TIMEOUT_MS, remaining_ms)
        provider.force_flush(timeout_ms)
    except Exception:  # noqa: BLE001
        logger.debug("opengrade: flush at exit raised", exc_info=True)
    for og in _all_tracing_instances():
        try:
            _teardown_instance_tracing(og)
        except Exception:  # noqa: BLE001
            logger.debug("opengrade: instance teardown at exit raised", exc_info=True)
    if _OWNS_SHARED_PROVIDER and _SHARED_PROVIDER is not None:
        try:
            _SHARED_PROVIDER.shutdown()
        except Exception:  # noqa: BLE001
            logger.debug("opengrade: tracer provider shutdown raised", exc_info=True)
        _SHARED_PROVIDER = None
        _ROUTER = None
        setattr(trace, "_TRACER_PROVIDER", None)  # noqa: B010
        setattr(trace, "_TRACER_PROVIDER_SET_ONCE", Once())  # noqa: B010


def release_attributes(version: str | None, environment: str | None) -> dict[str, str]:
    """Resource keys (``service.version`` …) plus ``opengrade.*`` span-level twins."""
    attrs: dict[str, str] = {}
    if version:
        attrs["service.version"] = attrs["opengrade.version"] = version
    if environment:
        attrs["deployment.environment"] = attrs["opengrade.environment"] = environment
    return attrs


def init_for_instance(
    og: Opengrade,
    *,
    project_id: str | None = None,
    project_slug: str | None = None,
    endpoint: str | None = None,
    service_name: str | None = None,
    instrument: Literal["auto", False] | Sequence[str] = "auto",
    force: bool = False,
    live: bool | None = None,
    live_sample_rate: float | None = None,
    trace_sample_rate: float | None = None,
    max_capture_bytes: int | None = None,
    metrics_workers: int | None = None,
    version: str | None = None,
    environment: str | None = None,
    **kwargs: Any,
) -> None:
    """Configure OTLP export for ``og`` through the shared process ``TracerProvider``."""
    global _SHARED_PROVIDER, _OWNS_SHARED_PROVIDER, _INSTRUMENTOR_OWNER

    span_exporter: SpanExporter | None = kwargs.pop("_span_exporter", None)
    if kwargs:
        logger.debug("opengrade: ignoring unknown init_tracing kwargs: %s", sorted(kwargs))

    rt = og._runtime
    is_default = rt is _state._default()

    if is_disabled():
        logger.info("opengrade: OPENGRADE_DISABLED is set; tracing disabled")
        return

    if rt.initialized and not force:
        if is_default:
            logger.info("opengrade already initialized; skipping (pass force=True to re-init)")
        return

    if force:
        if is_default:
            deactivate_instrumentors()
        _teardown_instance_tracing(og)

    if is_default:
        try:
            _live.configure(enabled=live, sample_rate=live_sample_rate)
        except (TypeError, ValueError) as exc:
            logger.warning("opengrade: live capture disabled: %s", exc)
            _live.configure(enabled=False)

        try:
            configure_capture(max_capture_bytes=max_capture_bytes)
        except (TypeError, ValueError) as exc:
            logger.warning("opengrade: max_capture_bytes ignored: %s", exc)
            configure_capture()

        try:
            _production.configure(workers=metrics_workers)
        except (TypeError, ValueError) as exc:
            logger.warning("opengrade: metrics_workers ignored: %s", exc)

    try:
        sample_rate = resolve_trace_sample_rate(trace_sample_rate)
    except (TypeError, ValueError) as exc:
        logger.warning("opengrade: trace_sample_rate ignored: %s", exc)
        sample_rate = 1.0

    settings = og.settings
    try:
        from opentelemetry.exporter.otlp.proto.http import Compression
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

        pid = project_id
        pslug = project_slug
        if pid is None and pslug is None and not is_default:
            pid = settings.project_id
            pslug = settings.project_slug
        config = resolve_config(
            project_id=pid,
            project_slug=pslug,
            endpoint=endpoint,
            service_name=service_name or settings.service_name,
            version=version or settings.version,
            environment=environment or settings.environment,
        )
        headers = {**project_headers(config), **auth_headers(config.endpoint)}
        release = release_attributes(config.version, config.environment)
        resource = Resource.create(
            {
                "service.name": config.service_name,
                **{k: v for k, v in release.items() if not k.startswith("opengrade.")},
            }
        )
        inner_exporter = (
            span_exporter
            if span_exporter is not None
            else OTLPSpanExporter(
                endpoint=config.endpoint,
                headers=headers,
                timeout=EXPORT_TIMEOUT_S,
                compression=Compression.Gzip,
                max_request_size=OTLP_MAX_REQUEST_BYTES,
            )
        )
        exporter: SpanExporter = (
            inner_exporter if span_exporter is not None else _SafeSpanExporter(inner_exporter)
        )
        processor: SpanProcessor = BatchSpanProcessor(
            exporter, max_export_batch_size=OTLP_MAX_EXPORT_BATCH_SIZE
        )
        release_span_attrs = {k: v for k, v in release.items() if k.startswith("opengrade.")}
        existing = trace.get_tracer_provider()

        router = _get_or_create_router()
        if isinstance(existing, TracerProvider):
            provider = existing
            if not _provider_has_router(provider, router):
                provider.add_span_processor(router)
            if _SHARED_PROVIDER is None:
                _OWNS_SHARED_PROVIDER = False
            _SHARED_PROVIDER = provider
        elif _SHARED_PROVIDER is None:
            sampler = ParentBased(root=TraceIdRatioBased(sample_rate))
            provider = TracerProvider(resource=resource, sampler=sampler, shutdown_on_exit=False)
            provider.add_span_processor(router)
            trace.set_tracer_provider(provider)
            _SHARED_PROVIDER = provider
            _OWNS_SHARED_PROVIDER = True
        else:
            provider = _SHARED_PROVIDER
            if not _provider_has_router(provider, router):
                provider.add_span_processor(router)

        router.register(og._instance_id, processor)
        if release_span_attrs:
            router.register_release_attrs(og._instance_id, release_span_attrs)
    except Exception as exc:  # noqa: BLE001 — init must never break the host app
        logger.warning("opengrade: tracing disabled, init failed: %s", exc)
        return

    otlp_logger = logging.getLogger(_OTLP_LOGGER_NAME)
    if _OTLP_LOG_FILTER not in otlp_logger.filters:
        otlp_logger.addFilter(_OTLP_LOG_FILTER)

    if instrument is not False:
        owner = _INSTRUMENTOR_OWNER() if _INSTRUMENTOR_OWNER is not None else None
        if owner is not None and owner is not og:
            logger.warning(
                "opengrade: OpenInference instrumentors are process-global and already "
                "activated for another Opengrade instance; skipping instrument=%r",
                instrument,
            )
        else:
            keys: Sequence[str] | None
            if instrument == "auto":
                keys = None
            else:
                keys = list(instrument)
            try:
                activate_instrumentors(keys, provider)
                _INSTRUMENTOR_OWNER = weakref.ref(og)
            except Exception as exc:  # noqa: BLE001
                logger.warning("opengrade: auto-instrumentation skipped: %s", exc)

    if is_default:
        from opengrade._config import _set_active_project

        if config.project_id:
            _set_active_project(project_id=config.project_id)
        elif config.project_slug:
            _set_active_project(project_slug=config.project_slug)

    rt.provider = provider
    rt.processor = processor
    rt.exporter = exporter
    rt.owns_provider = _OWNS_SHARED_PROVIDER
    rt.initialized = True
    og.tracing_enabled = True
    _OPEN_TRACING_INSTANCES.add(og)
    if not _atexit_registered():
        atexit.register(_at_exit)
        _mark_atexit_registered()


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
    trace_sample_rate: float | None = None,
    max_capture_bytes: int | None = None,
    metrics_workers: int | None = None,
    version: str | None = None,
    environment: str | None = None,
) -> None:
    """Configure OTLP export for the default ``Opengrade`` instance (module facade)."""
    from opengrade._opengrade import _default_opengrade

    init_for_instance(
        _default_opengrade(),
        project_id=project_id,
        project_slug=project_slug,
        endpoint=endpoint,
        service_name=service_name,
        instrument=instrument,
        force=force,
        live=live,
        live_sample_rate=live_sample_rate,
        trace_sample_rate=trace_sample_rate,
        max_capture_bytes=max_capture_bytes,
        metrics_workers=metrics_workers,
        version=version,
        environment=environment,
    )


def flush(timeout_millis: int = 5000) -> bool:
    """Flush spans, then production metrics, then queued trace scores.

    ``timeout_millis`` is the total budget: each stage gets what the previous left.
    Metrics are drained before scores are flushed because they produce scores.
    """
    deadline = time.monotonic() + timeout_millis / 1000
    ok = True
    provider = _current_provider()
    if provider is not None:
        try:
            ok = bool(provider.force_flush(timeout_millis))
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


def __getattr__(name: str) -> Any:
    rt = _state._default()
    if name == "_PROVIDER":
        return rt.provider
    if name == "_PROCESSOR":
        return rt.processor
    if name == "_EXPORTER":
        return rt.exporter
    if name == "_OWNS_PROVIDER":
        return rt.owns_provider
    if name == "_INITIALIZED":
        return rt.initialized
    if name == "_ATEXIT_REGISTERED":
        return rt.otel_atexit_registered
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
