from __future__ import annotations

import functools
import inspect
import json
import logging
from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from contextlib import contextmanager
from typing import Any, cast, overload

from opentelemetry import trace as otel_trace
from opentelemetry.trace import Span, Status, StatusCode

from opengrade import _live, _production, _trace_attrs
from opengrade._config import capture_redact, capture_redact_output, max_capture_bytes
from opengrade._run_context import record_input, record_output
from opengrade.metrics import LocalMetric

_TRACER_NAME = "opengrade"
_TRUNCATE_MARKER = "…[truncated]"


def _leaf_str(value: object) -> str:
    try:
        return str(value)
    except Exception:  # noqa: BLE001
        return f"<unserializable {type(value).__name__}>"


def _budget_reduce(value: object, budget: list[int]) -> object:
    """Shrink ``value`` so a later ``json.dumps`` stays near ``budget[0]`` UTF-8 bytes."""
    if budget[0] <= 0:
        return _TRUNCATE_MARKER

    if isinstance(value, str):
        raw = value.encode("utf-8")
        if len(raw) <= budget[0]:
            budget[0] -= len(raw)
            return value
        clipped = raw[: budget[0]].decode("utf-8", errors="ignore")
        budget[0] = 0
        return clipped + _TRUNCATE_MARKER

    if isinstance(value, dict):
        out: dict[str, object] = {}
        for key, item in value.items():
            if budget[0] <= 0:
                break
            key_text = key if isinstance(key, str) else _leaf_str(key)
            key_cost = len(key_text.encode("utf-8")) + 3  # rough JSON overhead
            if key_cost >= budget[0]:
                break
            budget[0] -= key_cost
            out[key_text] = _budget_reduce(item, budget)
        return out

    if isinstance(value, (list, tuple)):
        out_list: list[object] = []
        for item in value:
            if budget[0] <= 0:
                break
            out_list.append(_budget_reduce(item, budget))
        return out_list

    if isinstance(value, bool) or value is None:
        budget[0] = max(0, budget[0] - 4)
        return value

    if isinstance(value, int) and not isinstance(value, bool):
        text = str(value)
        budget[0] = max(0, budget[0] - len(text.encode("utf-8")))
        return value

    if isinstance(value, float):
        text = str(value)
        budget[0] = max(0, budget[0] - len(text.encode("utf-8")))
        return value

    return _budget_reduce(_leaf_str(value), budget)


def truncate_value(value: object, *, limit: int | None = None) -> str:
    if limit is None:
        limit = max_capture_bytes()
    try:
        if isinstance(value, str):
            reduced: object = value
        else:
            reduced = _budget_reduce(value, [limit])
        if isinstance(reduced, str):
            text = reduced
        else:
            try:
                text = json.dumps(reduced, default=str)
            except Exception:  # noqa: BLE001
                text = _leaf_str(reduced)
    except Exception:  # noqa: BLE001
        text = _leaf_str(value)

    raw = text.encode("utf-8")
    if len(raw) <= limit:
        return text
    budget = max(0, limit - len(_TRUNCATE_MARKER.encode("utf-8")))
    clipped = raw[:budget].decode("utf-8", errors="ignore")
    return clipped + _TRUNCATE_MARKER


def _attr_or_key(obj: object, name: str) -> object:
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _chunk_text(chunk: object) -> str:
    if isinstance(chunk, str):
        return chunk
    content = _attr_or_key(chunk, "content")
    if isinstance(content, str):
        return content
    delta = _attr_or_key(chunk, "delta")
    if delta is not None:
        delta_content = _attr_or_key(delta, "content")
        if isinstance(delta_content, str):
            return delta_content
    choices = _attr_or_key(chunk, "choices")
    if isinstance(choices, (list, tuple)) and choices:
        first = choices[0]
        nested_delta = _attr_or_key(first, "delta")
        if nested_delta is not None:
            nested_content = _attr_or_key(nested_delta, "content")
            if isinstance(nested_content, str):
                return nested_content
    text = _attr_or_key(chunk, "text")
    if isinstance(text, str):
        return text
    return ""


def _default_join_chunks(chunk: object, acc: object) -> object:
    base = "" if acc is None else acc
    if not isinstance(base, str):
        base = _leaf_str(base)
    if base.endswith(_TRUNCATE_MARKER):
        return base
    piece = _chunk_text(chunk)
    if not piece:
        return base
    limit = max_capture_bytes()
    combined = base + piece
    raw = combined.encode("utf-8")
    if len(raw) <= limit:
        return combined
    budget = max(0, limit - len(_TRUNCATE_MARKER.encode("utf-8")))
    clipped = raw[:budget].decode("utf-8", errors="ignore")
    return clipped + _TRUNCATE_MARKER


def _default_name(fn: Callable[..., Any]) -> str:
    module = getattr(fn, "__module__", "")
    qual = getattr(fn, "__qualname__", getattr(fn, "__name__", "span"))
    return f"{module}.{qual}" if module else qual


def _resolve_redact(
    override: Callable[[str, Any], Any] | None,
) -> Callable[[str, Any], Any] | None:
    return override if override is not None else capture_redact()


def _resolve_redact_output(
    override: Callable[[Any], Any] | None,
) -> Callable[[Any], Any] | None:
    return override if override is not None else capture_redact_output()


def _bind_arguments(
    fn: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]
) -> dict[str, Any]:
    try:
        target = _unwrap_partial(fn)
        bound = inspect.signature(target).bind_partial(*args, **kwargs)
        bound.apply_defaults()
        mapping = dict(bound.arguments)
    except Exception:  # noqa: BLE001
        mapping = {str(i): v for i, v in enumerate(args)}
        mapping.update(kwargs)
    mapping.pop("self", None)
    mapping.pop("cls", None)
    return mapping


def _apply_redact(
    payload: dict[str, Any], redact: Callable[[str, Any], Any] | None
) -> dict[str, Any]:
    if redact is None:
        return payload
    out: dict[str, Any] = {}
    for name, value in payload.items():
        try:
            out[name] = redact(name, value)
        except Exception:  # noqa: BLE001
            out[name] = "<redact error>"
    return out


def _serialize_args(
    fn: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    *,
    redact: Callable[[str, Any], Any] | None = None,
) -> str:
    try:
        payload = _apply_redact(_bind_arguments(fn, args, kwargs), _resolve_redact(redact))
        return truncate_value(payload)
    except Exception:  # noqa: BLE001
        return "<unserializable args>"


def _unwrap_partial(fn: Callable[..., Any]) -> Callable[..., Any]:
    while isinstance(fn, functools.partial):
        fn = fn.func
    return fn


def _current_span() -> Span:
    return otel_trace.get_current_span()


_INT64_MIN = -(2**63)
_INT64_MAX = 2**63 - 1


def _attr_value(value: object) -> bool | int | float | str:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        if value < _INT64_MIN or value > _INT64_MAX:
            return str(value)
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
    """Set OpenInference ``output.value`` on the current span (and production metrics' output)."""
    record_output(value, _current_span())
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


def _start_attributes(span: Span, kind: str) -> None:
    span.set_attribute("openinference.span.kind", kind)
    _trace_attrs.apply_scoped(span)


@contextmanager
def _span_session(
    span_name: str,
    *,
    kind: str,
    capture_input: bool,
    live: bool | None,
    production: tuple[LocalMetric, ...],
    fn: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    redact: Callable[[str, Any], Any] | None = None,
) -> Iterator[tuple[Span, Any]]:
    """Open a span; yield ``(span, capture_token)``. Caller ends metrics via ``_finish_span``."""
    tracer = otel_trace.get_tracer(_TRACER_NAME)
    with tracer.start_as_current_span(
        span_name, record_exception=False, set_status_on_exception=False
    ) as span:
        _start_attributes(span, kind)
        if capture_input and span.is_recording():
            span.set_attribute("input.value", _serialize_args(fn, args, kwargs, redact=redact))
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
    redact_output: Callable[[Any], Any] | None = None,
) -> None:
    capture = _production.stop(capture_token)
    value = result
    redactor = _resolve_redact_output(redact_output)
    if redactor is not None:
        try:
            value = redactor(result)
        except Exception:  # noqa: BLE001
            value = "<redact error>"
    if capture_output and span.is_recording():
        span.set_attribute("output.value", truncate_value(value))
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
    redact: Callable[[str, Any], Any] | None = None,
    redact_output: Callable[[Any], Any] | None = None,
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
            fn=fn,
            args=args,
            kwargs=kwargs,
            redact=redact,
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
                redact_output=redact_output,
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
    redact: Callable[[str, Any], Any] | None = None,
    redact_output: Callable[[Any], Any] | None = None,
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
            fn=fn,
            args=args,
            kwargs=kwargs,
            redact=redact,
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
                redact_output=redact_output,
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
    redact: Callable[[str, Any], Any] | None = None,
    redact_output: Callable[[Any], Any] | None = None,
    join_chunks: Callable[[Any, Any], Any] | None = None,
) -> Callable[P, R]:
    reducer = join_chunks if join_chunks is not None else _default_join_chunks

    @functools.wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
        if _production.in_metric():
            yield from cast(Iterator[Any], fn(*args, **kwargs))
            return

        tracer = otel_trace.get_tracer(_TRACER_NAME)
        span = tracer.start_span(
            span_name, record_exception=False, set_status_on_exception=False
        )
        _start_attributes(span, kind)
        if capture_input and span.is_recording():
            span.set_attribute(
                "input.value", _serialize_args(fn, args, kwargs, redact=redact)
            )
        live_token = _live.mark_if_live(span, live)
        capture_token = _production.start(production, span)
        acc: Any = None
        join_failed = False
        finished = False
        gen: Iterator[Any] | None = None

        def finish(result: Any) -> None:
            nonlocal finished
            if finished:
                return
            finished = True
            _live.unmark(live_token)
            _finish_span(
                span,
                capture_token=capture_token,
                capture_output=capture_output,
                production=production,
                rate=rate,
                args=args,
                kwargs=kwargs,
                result=result if capture_output else None,
                fn=fn,
                redact_output=redact_output,
            )
            span.end()

        try:
            gen = cast(Iterator[Any], fn(*args, **kwargs))
            while True:
                try:
                    with otel_trace.use_span(span, end_on_exit=False):
                        item = next(gen)
                except StopIteration:
                    break
                if capture_output and not join_failed:
                    try:
                        acc = reducer(item, acc)
                    except Exception:  # noqa: BLE001
                        acc = "<join error>"
                        join_failed = True
                yield item
        except Exception as exc:
            _record_error(span, exc)
            raise
        finally:
            finish(acc if capture_output else None)
            if gen is not None:
                try:
                    gen.close()
                except Exception:  # noqa: BLE001
                    pass

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
    redact: Callable[[str, Any], Any] | None = None,
    redact_output: Callable[[Any], Any] | None = None,
    join_chunks: Callable[[Any, Any], Any] | None = None,
) -> Callable[P, R]:
    reducer = join_chunks if join_chunks is not None else _default_join_chunks

    @functools.wraps(fn)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
        if _production.in_metric():
            async for item in cast(AsyncIterator[Any], fn(*args, **kwargs)):
                yield item
            return

        tracer = otel_trace.get_tracer(_TRACER_NAME)
        span = tracer.start_span(
            span_name, record_exception=False, set_status_on_exception=False
        )
        _start_attributes(span, kind)
        if capture_input and span.is_recording():
            span.set_attribute(
                "input.value", _serialize_args(fn, args, kwargs, redact=redact)
            )
        live_token = _live.mark_if_live(span, live)
        capture_token = _production.start(production, span)
        acc: Any = None
        join_failed = False
        finished = False
        gen: AsyncIterator[Any] | None = None

        def finish(result: Any) -> None:
            nonlocal finished
            if finished:
                return
            finished = True
            _live.unmark(live_token)
            _finish_span(
                span,
                capture_token=capture_token,
                capture_output=capture_output,
                production=production,
                rate=rate,
                args=args,
                kwargs=kwargs,
                result=result if capture_output else None,
                fn=fn,
                redact_output=redact_output,
            )
            span.end()

        try:
            gen = cast(AsyncIterator[Any], fn(*args, **kwargs))
            while True:
                try:
                    with otel_trace.use_span(span, end_on_exit=False):
                        item = await gen.__anext__()
                except StopAsyncIteration:
                    break
                if capture_output and not join_failed:
                    try:
                        acc = reducer(item, acc)
                    except Exception:  # noqa: BLE001
                        acc = "<join error>"
                        join_failed = True
                yield item
        except Exception as exc:
            _record_error(span, exc)
            raise
        finally:
            finish(acc if capture_output else None)
            if gen is not None:
                aclose = getattr(gen, "aclose", None)
                if aclose is not None:
                    try:
                        await aclose()
                    except Exception:  # noqa: BLE001
                        pass

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
    redact: Callable[[str, Any], Any] | None = None,
    redact_output: Callable[[Any], Any] | None = None,
    join_chunks: Callable[[Any, Any], Any] | None = None,
) -> Callable[..., Any]:
    if production:
        target = _unwrap_partial(fn)
        if inspect.isasyncgenfunction(target) or inspect.isgeneratorfunction(target):
            raise TypeError(
                "@opengrade.trace(metrics=...) needs a function returning its result; "
                f"got {fn!r}: generators are not supported with metrics="
            )
        elif not _production._is_coroutine_function(fn):
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
            redact=redact,
            redact_output=redact_output,
            join_chunks=join_chunks,
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
            redact=redact,
            redact_output=redact_output,
            join_chunks=join_chunks,
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
            redact=redact,
            redact_output=redact_output,
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
        redact=redact,
        redact_output=redact_output,
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
    redact: Callable[[str, Any], Any] | None = None,
    redact_output: Callable[[Any], Any] | None = None,
    join_chunks: Callable[[Any, Any], Any] | None = None,
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
    redact: Callable[[str, Any], Any] | None = None,
    redact_output: Callable[[Any], Any] | None = None,
    join_chunks: Callable[[Any, Any], Any] | None = None,
) -> Any:
    """Trace a function as an OpenInference span.

    Dispatches on function kind: sync, ``async def``, generator, or async generator.
    For generator and async-generator functions the span is current only during each
    advance (``next()`` / ``__anext__``); between yields it is not the active context.
    Streamed chunks are accumulated into ``output.value``: plain strings and common
    LLM delta shapes are joined as text by default. Pass ``join_chunks(chunk, acc)``
    to replace that reducer (``acc`` starts as ``None``); join errors are stored as
    ``"<join error>"``. Plain sync/async functions ignore ``join_chunks``.

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
                redact=redact,
                redact_output=redact_output,
                join_chunks=join_chunks,
            ),
        )

    if callable(name):
        fn = name
        name = None
        return decorator(fn)
    return decorator


# OpenInference span kinds (``openinference.span.kind``); anything else is sent as-is.
SPAN_KINDS = frozenset(
    {
        "CHAIN",
        "LLM",
        "RETRIEVER",
        "RERANKER",
        "EMBEDDING",
        "TOOL",
        "AGENT",
        "GUARDRAIL",
        "EVALUATOR",
        "PROMPT",
    }
)

_warned_kinds: set[str] = set()


def _normalize_kind(kind: str) -> str:
    normalized = (kind or "CHAIN").strip().upper() or "CHAIN"
    if normalized not in SPAN_KINDS and normalized not in _warned_kinds:
        _warned_kinds.add(normalized)
        logging.getLogger("opengrade").warning(
            "opengrade: span kind %r is not an OpenInference kind (%s); sent as-is",
            kind,
            ", ".join(sorted(SPAN_KINDS)),
        )
    return normalized


class SpanHandle:
    """The span opened by ``opengrade.span``; every method is a no-op when not recording."""

    __slots__ = ("_span",)

    def __init__(self, span: Span | None) -> None:
        self._span = span

    @property
    def is_recording(self) -> bool:
        return self._span is not None and self._span.is_recording()

    @property
    def trace_id(self) -> str | None:
        if self._span is None:
            return None
        ctx = self._span.get_span_context()
        return format(ctx.trace_id, "032x") if ctx.is_valid else None

    @property
    def span_id(self) -> str | None:
        if self._span is None:
            return None
        ctx = self._span.get_span_context()
        return format(ctx.span_id, "016x") if ctx.is_valid else None

    def set_input(self, value: object) -> None:
        """Set ``input.value`` on this span (the experiment / production input is unchanged)."""
        if self.is_recording:
            assert self._span is not None
            self._span.set_attribute("input.value", truncate_value(value))

    def set_output(self, value: object) -> None:
        """Set ``output.value`` on this span (the experiment output is unchanged)."""
        if self.is_recording:
            assert self._span is not None
            self._span.set_attribute("output.value", truncate_value(value))

    def set_attribute(self, key: str, value: object) -> None:
        if self.is_recording:
            assert self._span is not None
            self._span.set_attribute(key, _attr_value(value))

    def set_attributes(self, attrs: dict[str, object] | None = None, **kwargs: object) -> None:
        for key, value in {**(attrs or {}), **kwargs}.items():
            self.set_attribute(key, value)

    def set_error(self, description: str, *, exception: BaseException | None = None) -> None:
        if not self.is_recording:
            return
        assert self._span is not None
        if exception is not None:
            self._span.record_exception(exception)
        self._span.set_status(Status(StatusCode.ERROR, description))


class span:  # noqa: N801 — used like a function: ``with opengrade.span(...)``
    """Trace a block of code as a child span (sync ``with`` or ``async with``).

    ::

        with opengrade.span("rerank", kind="RERANKER", input=query) as s:
            ranked = reranker.rank(query, docs)
            s.set_output([d.id for d in ranked])
            s.set_attribute("rerank.top_k", 5)

    ``kind`` is an OpenInference span kind (``CHAIN``, ``LLM``, ``RETRIEVER``,
    ``RERANKER``, ``EMBEDDING``, ``TOOL``, ``AGENT``, ``GUARDRAIL``, ...). An exception
    raised in the block marks the span ERROR and propagates. Like ``@opengrade.trace``,
    the outermost span outside an experiment becomes a live interaction when
    ``init(live=True)``; pass ``live=False`` to opt out.
    """

    __slots__ = ("_name", "_kind", "_input", "_attributes", "_live", "_cm", "_span", "_live_token")

    def __init__(
        self,
        name: str,
        kind: str = "CHAIN",
        *,
        input: object = None,  # noqa: A002 — mirrors OpenInference ``input.value``
        attributes: dict[str, object] | None = None,
        live: bool | None = None,
    ) -> None:
        self._name = name or "span"
        self._kind = _normalize_kind(kind)
        self._input = input
        self._attributes = attributes
        self._live = live
        self._cm: Any = None
        self._span: Span | None = None
        self._live_token: Any = None

    def __enter__(self) -> SpanHandle:
        if self._cm is not None:
            raise RuntimeError("opengrade.span(...) is not reentrant; create a new one")
        if _production.in_metric():
            return SpanHandle(None)  # metrics run with instrumentation suppressed
        tracer = otel_trace.get_tracer(_TRACER_NAME)
        self._cm = tracer.start_as_current_span(
            self._name, record_exception=False, set_status_on_exception=False
        )
        current = self._cm.__enter__()
        self._span = current
        handle = SpanHandle(current)
        _start_attributes(current, self._kind)
        if self._input is not None:
            handle.set_input(self._input)
        if self._attributes:
            handle.set_attributes(self._attributes)
        self._live_token = _live.mark_if_live(current, self._live)
        return handle

    def __exit__(self, exc_type: Any, exc: BaseException | None, tb: Any) -> None:
        cm, current = self._cm, self._span
        self._cm = self._span = None
        if cm is None or current is None:
            return
        _live.unmark(self._live_token)
        self._live_token = None
        if isinstance(exc, Exception):
            _record_error(current, exc)
        cm.__exit__(exc_type, exc, tb)

    async def __aenter__(self) -> SpanHandle:
        return self.__enter__()

    async def __aexit__(self, exc_type: Any, exc: BaseException | None, tb: Any) -> None:
        self.__exit__(exc_type, exc, tb)
