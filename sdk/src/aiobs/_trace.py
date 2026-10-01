from __future__ import annotations

import functools
import json
from collections.abc import Callable
from typing import Any, ParamSpec, TypeVar, overload

from opentelemetry import trace as otel_trace
from opentelemetry.trace import Status, StatusCode

from aiobs._config import MAX_CAPTURE_BYTES

P = ParamSpec("P")
R = TypeVar("R")

_TRACER_NAME = "aiobs"
_TRUNCATE_MARKER = "…[truncated]"


def truncate_value(value: object, *, limit: int = MAX_CAPTURE_BYTES) -> str:
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, default=str)
        except TypeError:
            text = str(value)
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


@overload
def trace(name: Callable[P, R]) -> Callable[P, R]: ...


@overload
def trace(
    name: str | None = None,
    *,
    kind: str = "CHAIN",
    capture_input: bool = True,
    capture_output: bool = True,
) -> Callable[[Callable[P, R]], Callable[P, R]]: ...


def trace(
    name: str | Callable[P, R] | None = None,
    *,
    kind: str = "CHAIN",
    capture_input: bool = True,
    capture_output: bool = True,
) -> Any:
    def decorator(fn: Callable[P, R]) -> Callable[P, R]:
        span_name = name if isinstance(name, str) and name else _default_name(fn)

        @functools.wraps(fn)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            tracer = otel_trace.get_tracer(_TRACER_NAME)
            with tracer.start_as_current_span(span_name) as span:
                span.set_attribute("openinference.span.kind", kind)
                if capture_input:
                    span.set_attribute("input.value", _serialize_args(args, kwargs))
                try:
                    result = fn(*args, **kwargs)
                except Exception as exc:
                    span.record_exception(exc)
                    span.set_status(Status(StatusCode.ERROR, str(exc)))
                    raise
                if capture_output:
                    span.set_attribute("output.value", truncate_value(result))
                return result

        return wrapper

    if callable(name):
        fn = name
        name = None
        return decorator(fn)
    return decorator


@overload
def trace_async(name: Callable[P, R]) -> Callable[P, R]: ...


@overload
def trace_async(
    name: str | None = None,
    *,
    kind: str = "CHAIN",
    capture_input: bool = True,
    capture_output: bool = True,
) -> Callable[[Callable[P, R]], Callable[P, R]]: ...


def trace_async(
    name: str | Callable[P, R] | None = None,
    *,
    kind: str = "CHAIN",
    capture_input: bool = True,
    capture_output: bool = True,
) -> Any:
    def decorator(fn: Callable[P, R]) -> Callable[P, R]:
        span_name = name if isinstance(name, str) and name else _default_name(fn)

        @functools.wraps(fn)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            tracer = otel_trace.get_tracer(_TRACER_NAME)
            with tracer.start_as_current_span(span_name) as span:
                span.set_attribute("openinference.span.kind", kind)
                if capture_input:
                    span.set_attribute("input.value", _serialize_args(args, kwargs))
                try:
                    result = await fn(*args, **kwargs)  # type: ignore[misc]
                except Exception as exc:
                    span.record_exception(exc)
                    span.set_status(Status(StatusCode.ERROR, str(exc)))
                    raise
                if capture_output:
                    span.set_attribute("output.value", truncate_value(result))
                return result

        return wrapper  # type: ignore[return-value]

    if callable(name):
        fn = name
        name = None
        return decorator(fn)
    return decorator
