from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Literal

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.util._once import Once

from aiobs._config import project_headers, resolve_config
from aiobs.instrumentation import activate_instrumentors

logger = logging.getLogger("aiobs")

_PROVIDER: TracerProvider | None = None
_INITIALIZED: bool = False


def _shutdown_and_reset_global_tracer_provider() -> None:
    global _PROVIDER
    shutdown_targets: set[TracerProvider] = set()
    if _PROVIDER is not None:
        shutdown_targets.add(_PROVIDER)
    otel_tp = trace._TRACER_PROVIDER  # type: ignore[attr-defined]
    if isinstance(otel_tp, TracerProvider):
        shutdown_targets.add(otel_tp)
    for provider in shutdown_targets:
        provider.shutdown()

    _PROVIDER = None
    trace._TRACER_PROVIDER = None  # type: ignore[attr-defined]
    trace._TRACER_PROVIDER_SET_ONCE = Once()  # type: ignore[attr-defined]


def _reset_for_tests() -> None:
    global _INITIALIZED
    _shutdown_and_reset_global_tracer_provider()
    _INITIALIZED = False


def init(
    *,
    project_id: str | None = None,
    project_slug: str | None = None,
    endpoint: str | None = None,
    service_name: str | None = None,
    instrument: Literal["auto", False] | Sequence[str] = "auto",
    force: bool = False,
) -> None:
    global _PROVIDER, _INITIALIZED

    if _INITIALIZED and not force:
        logger.info("aiobs already initialized; skipping (pass force=True to re-init)")
        return

    if force:
        _shutdown_and_reset_global_tracer_provider()

    config = resolve_config(
        project_id=project_id,
        project_slug=project_slug,
        endpoint=endpoint,
        service_name=service_name,
    )
    headers = project_headers(config)
    resource = Resource.create({"service.name": config.service_name})
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=config.endpoint, headers=headers)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    if instrument is not False:
        keys: Sequence[str] | None
        if instrument == "auto":
            keys = None  # means all registered
        else:
            keys = list(instrument)
        activate_instrumentors(keys, provider)

    _PROVIDER = provider
    _INITIALIZED = True


def flush(timeout_millis: int = 5000) -> bool:
    if _PROVIDER is None:
        return True
    return bool(_PROVIDER.force_flush(timeout_millis))
