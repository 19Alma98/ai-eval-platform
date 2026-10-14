from __future__ import annotations

import functools
import json
from collections.abc import Callable, Sequence
from typing import Any, cast, overload

from opentelemetry import trace as otel_trace
from opentelemetry.trace import Span, Status, StatusCode

from aiobs import _live, _production
from aiobs._config import MAX_CAPTURE_BYTES
from aiobs._run_context import record_input, record_output
from aiobs.metrics import LocalMetric

_TRACER_NAME = "aiobs"
_TRUNCATE_MARKER = "…[truncated]"


def truncate_value(value: object, *, limit: int = MAX_CAPTURE_BYTES) -> str:
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, default=str)
        except Exception:  # noqa: BLE001 — capture must never break the traced call
            try:
                text = str(value)
            except Exception:  # noqa: BLE001
                text = f"<unserializable {type(value).__name__}>"
    raw = text.encode("utf-8")
    if len(raw) <= limit:
        return text
    budget = max(0, limit - len(_TRUNCATE_MARKER.encode("utf-8")))
    clipped = raw[:budget].decode("utf-8", errors="ignore")
    return clipped + _TRUNCATE_MARKER


def _default_name(fn: Callable[..., Any]) -> str:
    module = getattr(fn, "__module__", "")
    qual = getattr(fn, "__qualname__", getattr(fn, "__name__", "span"))
    return f"{module}.{qual}" if module else qual


def _serialize_args(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    payload = {"args": list(args), "kwargs": kwargs}
    return truncate_value(payload)


def _current_span() -> Span:
    return otel_trace.get_current_span()


def _attr_value(value: object) -> bool | int | float | str:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        return value
    return truncate_value(value)


def set_attribute(key: str, value: object) -> None:
    """Set one attribute on the current aiobs span (no-op if none is active)."""
    span = _current_span()
    if not span.is_recording():
        return
    span.set_attribute(key, _attr_value(value))


def set_attributes(attrs: dict[str, object] | None = None, **kwargs: object) -> None:
    """Set multiple attributes on the current aiobs span."""
    merged: dict[str, object] = {}
    if attrs:
        merged.update(attrs)
    merged.update(kwargs)
    for key, value in merged.items():
        set_attribute(key, value)


def set_input(value: object) -> None:
    """Set OpenInference ``input.value`` on the current span (and production metrics' input)."""
    record_input(value, _current_span())
    set_attribute("input.value", value)


def set_output(value: object) -> None:
    """Set OpenInference ``output.value`` on the current span."""
    record_output(value)
    set_attribute("output.value", value)


def set_error(description: str, *, exception: BaseException | None = None) -> None:
    """Mark the current span as ERROR (optionally attach an exception)."""
    span = _current_span()
    if not span.is_recording():
        return
    if exception is not None:
        span.record_exception(exception)
    span.set_status(Status(StatusCode.ERROR, description))


def current_trace_id() -> str | None:
    """Return the current OTLP trace id as 32-char hex, or None if inactive."""
    span = _current_span()
    ctx = span.get_span_context()
    if ctx is None or not ctx.is_valid:
        return None
    return format(ctx.trace_id, "032x")


@overload
def trace[**P, R](name: Callable[P, R]) -> Callable[P, R]: ...


@overload
def trace[**P, R](
    name: str | None = None,
    *,
    kind: str = "CHAIN",
    capture_input: bool = True,
    capture_output: bool = True,
    live: bool | None = None,
    metrics: Sequence[LocalMetric | Callable[..., Any]] | None = None,
    metrics_sample_rate: float = 1.0,
) -> Callable[[Callable[P, R]], Callable[P, R]]: ...


def trace[**P, R](
    name: str | Callable[P, R] | None = None,
    *,
    kind: str = "CHAIN",
    capture_input: bool = True,
    capture_output: bool = True,
    live: bool | None = None,
    metrics: Sequence[LocalMetric | Callable[..., Any]] | None = None,
    metrics_sample_rate: float = 1.0,
) -> Any:
    """Trace a function as an OpenInference span.

    ``metrics=[...]`` scores each sampled production call after it returns (off the
    request path) and stores the results as trace scores; ``metrics_sample_rate`` is
    the fraction of traces scored, deterministic per trace. Skipped inside experiments.

    Metrics run on a background pool (default ``_production.MAX_WORKERS`` threads;
    set ``init(metrics_workers=...)`` or ``AIOBS_METRICS_WORKERS``). For slow metrics
    such as LLM judges, raise the worker count or lower ``metrics_sample_rate``.
    An async metric is cancelled after ``_production.METRIC_TIMEOUT_S`` (60 s) and
    counted as failed; a sync metric cannot be interrupted. Calls that a metric makes
    to ``@aiobs.trace`` functions are not traced (and not scored).
    """
    production = _production.normalize_metrics(metrics)
    rate = _production.parse_sample_rate(metrics_sample_rate)

    def decorator(fn: Callable[P, R]) -> Callable[P, R]:
        if production:
            _production.check_function(fn, is_async=False)
        span_name = name if isinstance(name, str) and name else _default_name(fn)

        @functools.wraps(fn)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            if _production.in_metric():  # metrics never create traces
                return fn(*args, **kwargs)
            tracer = otel_trace.get_tracer(_TRACER_NAME)
            with tracer.start_as_current_span(span_name) as span:
                span.set_attribute("openinference.span.kind", kind)
                if capture_input:
                    span.set_attribute("input.value", _serialize_args(args, kwargs))
                live_token = _live.mark_if_live(span, live)
                capture_token = _production.start(production, span)
                try:
                    result = fn(*args, **kwargs)
                except Exception as exc:
                    span.record_exception(exc)
                    span.set_status(Status(StatusCode.ERROR, str(exc)))
                    raise
                finally:
                    _live.unmark(live_token)
                    capture = _production.stop(capture_token)
                if capture_output:
                    span.set_attribute("output.value", truncate_value(result))
                if capture is not None:
                    _production.after_call(production, rate, span, capture, args, kwargs, result)
                return result

        return wrapper

    if callable(name):
        fn = name
        name = None
        return decorator(fn)
    return decorator


@overload
def trace_async[**P, R](name: Callable[P, R]) -> Callable[P, R]: ...


@overload
def trace_async[**P, R](
    name: str | None = None,
    *,
    kind: str = "CHAIN",
    capture_input: bool = True,
    capture_output: bool = True,
    live: bool | None = None,
    metrics: Sequence[LocalMetric | Callable[..., Any]] | None = None,
    metrics_sample_rate: float = 1.0,
) -> Callable[[Callable[P, R]], Callable[P, R]]: ...


def trace_async[**P, R](
    name: str | Callable[P, R] | None = None,
    *,
    kind: str = "CHAIN",
    capture_input: bool = True,
    capture_output: bool = True,
    live: bool | None = None,
    metrics: Sequence[LocalMetric | Callable[..., Any]] | None = None,
    metrics_sample_rate: float = 1.0,
) -> Any:
    """Async ``trace``: same ``metrics=`` / ``metrics_sample_rate=`` behaviour."""
    production = _production.normalize_metrics(metrics)
    rate = _production.parse_sample_rate(metrics_sample_rate)

    def decorator(fn: Callable[P, R]) -> Callable[P, R]:
        if production:
            _production.check_function(fn, is_async=True)
        span_name = name if isinstance(name, str) and name else _default_name(fn)

        @functools.wraps(fn)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            if _production.in_metric():  # metrics never create traces
                return cast(R, await fn(*args, **kwargs))  # type: ignore[misc]
            tracer = otel_trace.get_tracer(_TRACER_NAME)
            with tracer.start_as_current_span(span_name) as span:
                span.set_attribute("openinference.span.kind", kind)
                if capture_input:
                    span.set_attribute("input.value", _serialize_args(args, kwargs))
                live_token = _live.mark_if_live(span, live)
                capture_token = _production.start(production, span)
                try:
                    result = cast(R, await fn(*args, **kwargs))  # type: ignore[misc]
                except Exception as exc:
                    span.record_exception(exc)
                    span.set_status(Status(StatusCode.ERROR, str(exc)))
                    raise
                finally:
                    _live.unmark(live_token)
                    capture = _production.stop(capture_token)
                if capture_output:
                    span.set_attribute("output.value", truncate_value(result))
                if capture is not None:
                    _production.after_call(production, rate, span, capture, args, kwargs, result)
                return result

        return cast(Callable[P, R], wrapper)

    if callable(name):
        fn = name
        name = None
        return decorator(fn)
    return decorator
