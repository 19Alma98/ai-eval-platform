from __future__ import annotations

import functools
import inspect
import json
from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from contextlib import contextmanager
from typing import Any, cast, overload

from opentelemetry import trace as otel_trace
from opentelemetry.trace import Span, Status, StatusCode

from opengrade import _live, _production
from opengrade._config import MAX_CAPTURE_BYTES
from opengrade._run_context import record_input, record_output
from opengrade.metrics import LocalMetric

_TRACER_NAME = "opengrade"
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


def _unwrap_partial(fn: Callable[..., Any]) -> Callable[..., Any]:
    while isinstance(fn, functools.partial):
        fn = fn.func
    return fn


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
    """Set one attribute on the current opengrade span (no-op if none is active)."""
    span = _current_span()
    if not span.is_recording():
        return
    span.set_attribute(key, _attr_value(value))


def set_attributes(attrs: dict[str, object] | None = None, **kwargs: object) -> None:
    """Set multiple attributes on the current opengrade span."""
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


@contextmanager
def _span_session(
    span_name: str,
    *,
    kind: str,
    capture_input: bool,
    live: bool | None,
    production: tuple[LocalMetric, ...],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> Iterator[tuple[Span, Any]]:
    """Open a span; yield ``(span, capture_token)``. Caller ends metrics via ``_finish_span``."""
    tracer = otel_trace.get_tracer(_TRACER_NAME)
    with tracer.start_as_current_span(span_name) as span:
        span.set_attribute("openinference.span.kind", kind)
        if capture_input and span.is_recording():
            span.set_attribute("input.value", _serialize_args(args, kwargs))
        live_token = _live.mark_if_live(span, live)
        capture_token = _production.start(production, span)
        try:
            yield span, capture_token
        finally:
            _live.unmark(live_token)


def _finish_span(
    span: Span,
    *,
    capture_token: Any,
    capture_output: bool,
    production: tuple[LocalMetric, ...],
    rate: float,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    result: Any,
    fn: Callable[..., Any] | None = None,
) -> None:
    capture = _production.stop(capture_token)
    if capture_output and span.is_recording():
        span.set_attribute("output.value", truncate_value(result))
    if capture is not None:
        _production.after_call(production, rate, span, capture, args, kwargs, result, fn=fn)


def _record_error(span: Span, exc: BaseException) -> None:
    span.record_exception(exc)
    span.set_status(Status(StatusCode.ERROR, str(exc)))


def _wrap_sync[**P, R](
    fn: Callable[P, R],
    *,
    span_name: str,
    kind: str,
    capture_input: bool,
    capture_output: bool,
    live: bool | None,
    production: tuple[LocalMetric, ...],
    rate: float,
) -> Callable[P, R]:
    @functools.wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        if _production.in_metric():
            return fn(*args, **kwargs)
        with _span_session(
            span_name,
            kind=kind,
            capture_input=capture_input,
            live=live,
            production=production,
            args=args,
            kwargs=kwargs,
        ) as (span, capture_token):
            try:
                result = fn(*args, **kwargs)
            except Exception as exc:
                _record_error(span, exc)
                _production.stop(capture_token)
                raise
            _finish_span(
                span,
                capture_token=capture_token,
                capture_output=capture_output,
                production=production,
                rate=rate,
                args=args,
                kwargs=kwargs,
                result=result,
                fn=fn,
            )
            return result

    return wrapper


def _wrap_async[**P, R](
    fn: Callable[P, R],
    *,
    span_name: str,
    kind: str,
    capture_input: bool,
    capture_output: bool,
    live: bool | None,
    production: tuple[LocalMetric, ...],
    rate: float,
) -> Callable[P, R]:
    @functools.wraps(fn)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        if _production.in_metric():
            return cast(R, await fn(*args, **kwargs))  # type: ignore[misc]
        with _span_session(
            span_name,
            kind=kind,
            capture_input=capture_input,
            live=live,
            production=production,
            args=args,
            kwargs=kwargs,
        ) as (span, capture_token):
            try:
                result = cast(R, await fn(*args, **kwargs))  # type: ignore[misc]
            except Exception as exc:
                _record_error(span, exc)
                _production.stop(capture_token)
                raise
            _finish_span(
                span,
                capture_token=capture_token,
                capture_output=capture_output,
                production=production,
                rate=rate,
                args=args,
                kwargs=kwargs,
                result=result,
                fn=fn,
            )
            return result

    return cast(Callable[P, R], wrapper)


def _wrap_sync_gen[**P, R](
    fn: Callable[P, R],
    *,
    span_name: str,
    kind: str,
    capture_input: bool,
    capture_output: bool,
    live: bool | None,
    production: tuple[LocalMetric, ...],
    rate: float,
) -> Callable[P, R]:
    @functools.wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
        if _production.in_metric():
            yield from cast(Iterator[Any], fn(*args, **kwargs))
            return

        tracer = otel_trace.get_tracer(_TRACER_NAME)
        with tracer.start_as_current_span(span_name) as span:
            span.set_attribute("openinference.span.kind", kind)
            if capture_input and span.is_recording():
                span.set_attribute("input.value", _serialize_args(args, kwargs))
            live_token = _live.mark_if_live(span, live)
            capture_token = _production.start(production, span)
            chunks: list[Any] = []
            try:
                for item in cast(Iterator[Any], fn(*args, **kwargs)):
                    chunks.append(item)
                    yield item
            except Exception as exc:
                _record_error(span, exc)
                raise
            finally:
                _live.unmark(live_token)
                result = chunks if capture_output else None
                _finish_span(
                    span,
                    capture_token=capture_token,
                    capture_output=capture_output,
                    production=production,
                    rate=rate,
                    args=args,
                    kwargs=kwargs,
                    result=result,
                    fn=fn,
                )

    return cast(Callable[P, R], wrapper)


def _wrap_async_gen[**P, R](
    fn: Callable[P, R],
    *,
    span_name: str,
    kind: str,
    capture_input: bool,
    capture_output: bool,
    live: bool | None,
    production: tuple[LocalMetric, ...],
    rate: float,
) -> Callable[P, R]:
    @functools.wraps(fn)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
        if _production.in_metric():
            async for item in cast(AsyncIterator[Any], fn(*args, **kwargs)):
                yield item
            return

        tracer = otel_trace.get_tracer(_TRACER_NAME)
        with tracer.start_as_current_span(span_name) as span:
            span.set_attribute("openinference.span.kind", kind)
            if capture_input and span.is_recording():
                span.set_attribute("input.value", _serialize_args(args, kwargs))
            live_token = _live.mark_if_live(span, live)
            capture_token = _production.start(production, span)
            chunks: list[Any] = []
            try:
                async for item in cast(AsyncIterator[Any], fn(*args, **kwargs)):
                    chunks.append(item)
                    yield item
            except Exception as exc:
                _record_error(span, exc)
                raise
            finally:
                _live.unmark(live_token)
                result = chunks if capture_output else None
                _finish_span(
                    span,
                    capture_token=capture_token,
                    capture_output=capture_output,
                    production=production,
                    rate=rate,
                    args=args,
                    kwargs=kwargs,
                    result=result,
                    fn=fn,
                )

    return cast(Callable[P, R], wrapper)


def _decorate(
    fn: Callable[..., Any],
    *,
    span_name: str,
    kind: str,
    capture_input: bool,
    capture_output: bool,
    live: bool | None,
    production: tuple[LocalMetric, ...],
    rate: float,
    metrics_require_async: bool | None,
) -> Callable[..., Any]:
    if production:
        target = _unwrap_partial(fn)
        if metrics_require_async is True:
            _production.check_function(fn, is_async=True)
        elif inspect.isasyncgenfunction(target) or inspect.isgeneratorfunction(target):
            raise TypeError(
                "@opengrade.trace(metrics=...) needs a function returning its result; "
                f"got {fn!r}: generators are not supported with metrics="
            )
        elif _production._is_coroutine_function(fn):
            # Unified @trace: async def is fine once the wrapper awaits.
            pass
        else:
            _production.check_function(fn, is_async=False)

    target = _unwrap_partial(fn)
    if inspect.isasyncgenfunction(target):
        return _wrap_async_gen(
            fn,
            span_name=span_name,
            kind=kind,
            capture_input=capture_input,
            capture_output=capture_output,
            live=live,
            production=production,
            rate=rate,
        )
    if inspect.isgeneratorfunction(target):
        return _wrap_sync_gen(
            fn,
            span_name=span_name,
            kind=kind,
            capture_input=capture_input,
            capture_output=capture_output,
            live=live,
            production=production,
            rate=rate,
        )
    if inspect.iscoroutinefunction(target) or getattr(fn, "_is_coroutine", False):
        return _wrap_async(
            fn,
            span_name=span_name,
            kind=kind,
            capture_input=capture_input,
            capture_output=capture_output,
            live=live,
            production=production,
            rate=rate,
        )
    return _wrap_sync(
        fn,
        span_name=span_name,
        kind=kind,
        capture_input=capture_input,
        capture_output=capture_output,
        live=live,
        production=production,
        rate=rate,
    )


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

    Dispatches on function kind: sync, ``async def``, generator, or async generator.
    The span stays open until the call (or stream) fully completes.

    ``metrics=[...]`` scores each sampled production call after it returns (off the
    request path) and stores the results as trace scores; ``metrics_sample_rate`` is
    the fraction of traces scored, deterministic per trace. Skipped inside experiments.
    Metrics are not supported on generator / async-generator functions.
    """
    production = _production.normalize_metrics(metrics)
    rate = _production.parse_sample_rate(metrics_sample_rate)

    def decorator(fn: Callable[P, R]) -> Callable[P, R]:
        span_name = name if isinstance(name, str) and name else _default_name(fn)
        return cast(
            Callable[P, R],
            _decorate(
                fn,
                span_name=span_name,
                kind=kind,
                capture_input=capture_input,
                capture_output=capture_output,
                live=live,
                production=production,
                rate=rate,
                metrics_require_async=None,
            ),
        )

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
    """Async ``trace``: same behaviour; kept for compatibility (``@trace`` also works)."""
    production = _production.normalize_metrics(metrics)
    rate = _production.parse_sample_rate(metrics_sample_rate)

    def decorator(fn: Callable[P, R]) -> Callable[P, R]:
        span_name = name if isinstance(name, str) and name else _default_name(fn)
        return cast(
            Callable[P, R],
            _decorate(
                fn,
                span_name=span_name,
                kind=kind,
                capture_input=capture_input,
                capture_output=capture_output,
                live=live,
                production=production,
                rate=rate,
                metrics_require_async=True if production else None,
            ),
        )

    if callable(name):
        fn = name
        name = None
        return decorator(fn)
    return decorator
