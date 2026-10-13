"""Production metrics on ``@aiobs.trace(metrics=...)``.

Each traced call records its input/documents in a contextvar; after the function
returns, a sampled call's metrics run on a small pool of daemon threads (never on the
request path) and their results are queued as trace scores.

Nothing here raises into, or blocks, the traced call: when the bounded job queue is
full the call is not scored (rate-limited warning), and a failing metric or worker
error is logged (rate-limited) instead of being lost.

Metrics run isolated from tracing: OTel instrumentation is suppressed and
``@aiobs.trace`` functions they call run untraced, so a metric (e.g. an LLM judge
built on traced helpers) never creates spans, live interactions or more metrics.
"""

from __future__ import annotations

import atexit
import functools
import inspect
import logging
import numbers
import os
import queue
import threading
import time
from collections.abc import Callable, Sequence
from contextvars import ContextVar, Token
from typing import Any

from opentelemetry import context as otel_context
from opentelemetry.trace import Span

from aiobs import _config, _live, _scores, feedback
from aiobs._run_context import ACTIVE_RUN, PRODUCTION_CAPTURE, ProductionCapture
from aiobs.metrics import LocalMetric, Sample, evaluate_metric, metric, missing_requirement

logger = logging.getLogger("aiobs")

MAX_WORKERS = 2
MAX_QUEUE = 1000
METRIC_TIMEOUT_S = 60.0  # per async metric call; a sync metric cannot be interrupted
_WARN_EVERY_S = 60.0

# The key OTel instrumentors check (opentelemetry.instrumentation.utils); the plain
# string is the legacy key some still read.
_SUPPRESS_KEY: str = getattr(
    otel_context, "_SUPPRESS_INSTRUMENTATION_KEY", "suppress_instrumentation"
)
_SUPPRESS_KEY_PLAIN = "suppress_instrumentation"

# True while a production metric runs: ``@aiobs.trace`` then just calls the function.
_IN_METRIC: ContextVar[bool] = ContextVar("aiobs_in_metric", default=False)


def in_metric() -> bool:
    return _IN_METRIC.get()


_Job = Callable[[], None]

_warned: dict[str, float] = {}
_warn_lock = threading.Lock()


def _warn(key: str, message: str, *args: Any) -> None:
    """WARNING at most once a minute per ``key``, DEBUG otherwise."""
    now = time.monotonic()
    with _warn_lock:
        last = _warned.get(key)
        loud = last is None or now - last >= _WARN_EVERY_S
        if loud:
            _warned[key] = now
    logger.log(logging.WARNING if loud else logging.DEBUG, message, *args)


class _MetricPool:
    """Daemon worker threads fed by a bounded queue; ``submit`` never blocks."""

    def __init__(self, workers: int, max_queue: int) -> None:
        self._workers = workers
        self._jobs: queue.Queue[_Job | None] = queue.Queue(maxsize=max_queue)
        self._cond = threading.Condition()
        self._threads: list[threading.Thread] = []
        self._pending = 0
        self._closed = False
        self.dropped = 0

    def submit(self, job: _Job) -> bool:
        with self._cond:
            if self._closed or not self._ensure_workers():
                return False
            try:
                self._jobs.put_nowait(job)
            except queue.Full:
                self.dropped += 1
            else:
                self._pending += 1
                return True
        _warn(
            "queue_full",
            "aiobs: production metrics queue full (%d); skipping metrics for this call",
            self._jobs.maxsize,
        )
        return False

    def _ensure_workers(self) -> bool:  # caller holds the lock
        self._threads = [t for t in self._threads if t.is_alive()]
        while len(self._threads) < self._workers:
            try:
                thread = threading.Thread(target=self._work, name="aiobs-metrics", daemon=True)
                thread.start()
            except RuntimeError as exc:  # out of threads / interpreter shutting down
                logger.debug("aiobs: could not start a metrics thread: %s", exc)
                break
            self._threads.append(thread)
        return bool(self._threads)

    def _work(self) -> None:
        while True:
            job = self._jobs.get()
            if job is None:
                return
            try:
                job()
            except Exception as exc:  # noqa: BLE001 — a worker must survive any job
                _warn("worker", "aiobs: production metrics failed: %s", feedback._describe(exc))
            finally:
                with self._cond:
                    self._pending -= 1
                    self._cond.notify_all()

    def drain(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        with self._cond:
            while self._pending:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._cond.wait(remaining)
            return True

    def close(self) -> None:
        with self._cond:
            self._closed = True
            threads = len(self._threads)
        for _ in range(threads):
            try:
                self._jobs.put_nowait(None)
            except queue.Full:
                break  # daemon threads: left blocked, they die with the process


_POOL: _MetricPool | None = None
_POOL_SIZE: tuple[int, int] = (MAX_WORKERS, MAX_QUEUE)
_LOCK = threading.Lock()
_ATEXIT_REGISTERED = False


def normalize_metrics(
    metrics: Sequence[LocalMetric | Callable[..., Any]] | None,
) -> tuple[LocalMetric, ...]:
    """``LocalMetric``s with unique names; raises ValueError at decoration time."""
    if not metrics:
        return ()
    out: list[LocalMetric] = []
    for item in metrics:
        if isinstance(item, LocalMetric):
            spec = item
        elif callable(item):
            spec = metric(item)
        else:
            raise TypeError(f"unsupported metric {item!r}")
        if not spec.name:
            raise ValueError(
                "production metrics need a name: use a named function or @aiobs.metric(name=...)"
            )
        out.append(spec)
    names = [m.name for m in out]
    if len(set(names)) != len(names):
        raise ValueError(f"duplicate metric names: {names}")
    return tuple(out)


def parse_sample_rate(value: object) -> float:
    message = f"metrics_sample_rate must be a number within [0, 1], got {value!r}"
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise ValueError(message)
    rate = float(value)
    if not 0.0 <= rate <= 1.0:  # also rejects NaN
        raise ValueError(message)
    return rate


def check_function(fn: Callable[..., Any], *, is_async: bool) -> None:
    """With metrics, the decorator must see the call's real result: reject the wrong kind."""
    if is_async:
        if not inspect.iscoroutinefunction(fn):
            raise TypeError(
                "@aiobs.trace_async(metrics=...) needs a coroutine function (async def); "
                f"got {fn!r}: use @aiobs.trace for regular functions"
            )
    elif (
        inspect.iscoroutinefunction(fn)
        or inspect.isgeneratorfunction(fn)
        or inspect.isasyncgenfunction(fn)
    ):
        raise TypeError(
            "@aiobs.trace(metrics=...) needs a regular function returning its result; "
            f"got {fn!r}: use @aiobs.trace_async for coroutine functions"
        )


def start(metrics: tuple[LocalMetric, ...], span: Span) -> Token[ProductionCapture | None] | None:
    """Open a capture for this call; None when there is nothing to score here."""
    if not metrics or ACTIVE_RUN.get() is not None or _IN_METRIC.get():
        return None  # experiments score their own metrics; metrics are never scored
    return PRODUCTION_CAPTURE.set(ProductionCapture(span=span))


def stop(token: Token[ProductionCapture | None] | None) -> ProductionCapture | None:
    if token is None:
        return None
    capture = PRODUCTION_CAPTURE.get()
    PRODUCTION_CAPTURE.reset(token)
    return capture


def call_input(args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
    """The only argument, else the only keyword argument, else ``{"args", "kwargs"}``."""
    if len(args) == 1 and not kwargs:
        return args[0]
    if len(kwargs) == 1 and not args:
        return next(iter(kwargs.values()))
    return {"args": list(args), "kwargs": dict(kwargs)}


def after_call(
    metrics: tuple[LocalMetric, ...],
    sample_rate: float,
    span: Span,
    capture: ProductionCapture,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    result: Any,
) -> None:
    """Schedule the metrics for a finished call; never raises into the caller."""
    try:
        ctx = span.get_span_context()
        if not span.is_recording() or not ctx.is_valid:
            return
        if not _live.should_judge(ctx.trace_id, sample_rate):
            return
        try:
            project_id = _config.resolve_project_id()
        except ValueError as exc:
            _warn("project", "aiobs: production metrics skipped: %s", exc)
            return
        sample = Sample(
            input=capture.input if capture.has_input else call_input(args, kwargs),
            output=result,
            documents=[dict(d) for d in capture.documents or []],
            trace_id=format(ctx.trace_id, "032x"),
        )
        _submit(metrics, sample, project_id)
    except Exception as exc:  # noqa: BLE001 — scoring must never break the traced call
        _warn("schedule", "aiobs: production metrics skipped: %s", feedback._describe(exc))


def _pool() -> _MetricPool:
    global _POOL, _ATEXIT_REGISTERED
    with _LOCK:
        if _POOL is None:
            _POOL = _MetricPool(*_POOL_SIZE)
        if not _ATEXIT_REGISTERED:
            atexit.register(_at_exit)
            _ATEXIT_REGISTERED = True
        return _POOL


def _submit(metrics: tuple[LocalMetric, ...], sample: Sample, project_id: str) -> bool:
    return _pool().submit(functools.partial(_run, metrics, sample, project_id))


def _run(metrics: tuple[LocalMetric, ...], sample: Sample, project_id: str) -> None:
    """Run a job isolated from tracing (see the module docstring)."""
    ctx = otel_context.set_value(_SUPPRESS_KEY, True)
    ctx = otel_context.set_value(_SUPPRESS_KEY_PLAIN, True, ctx)
    otel_token = otel_context.attach(ctx)
    metric_token = _IN_METRIC.set(True)
    try:
        _run_metrics(metrics, sample, project_id)
    finally:
        _IN_METRIC.reset(metric_token)
        otel_context.detach(otel_token)


def _run_metrics(metrics: tuple[LocalMetric, ...], sample: Sample, project_id: str) -> None:
    trace_id = sample.trace_id or ""
    for spec in metrics:
        missing = missing_requirement(sample, spec.requires)
        if missing is not None:
            logger.debug("aiobs: metric %s skipped in production: missing %s", spec.name, missing)
            continue
        try:
            result = evaluate_metric(spec, sample, timeout=METRIC_TIMEOUT_S)
        except TimeoutError as exc:
            _warn(
                f"metric:{spec.name}",
                "aiobs: production metric %r timed out on trace %s (async limit %ss): %s",
                spec.name,
                trace_id,
                METRIC_TIMEOUT_S,
                feedback._describe(exc),
            )
            continue
        except Exception as exc:  # noqa: BLE001 — one broken metric must not stop the others
            _warn(
                f"metric:{spec.name}",
                "aiobs: production metric %r failed on trace %s: %s",
                spec.name,
                trace_id,
                feedback._describe(exc),
            )
            continue
        feedback.queue_metric_score(project_id, trace_id, spec, result)


def drain(timeout: float) -> bool:
    """Wait for scheduled metrics to finish (bounded); False on timeout."""
    current = _POOL
    return True if current is None else current.drain(timeout)


def dropped() -> int:
    """Calls not scored because the job queue was full."""
    current = _POOL
    return 0 if current is None else current.dropped


def _at_exit() -> None:
    """Finish pending metrics, then send their scores, within the shared exit budget."""
    try:
        drain(_scores.exit_remaining())
        _scores.flush(_scores.exit_remaining())
    except Exception:  # noqa: BLE001 — never raise during interpreter shutdown
        logger.debug("aiobs: production metrics drain at exit failed", exc_info=True)


def _reset_for_tests(*, workers: int = MAX_WORKERS, max_queue: int = MAX_QUEUE) -> None:
    """Drop the shared pool (rebuilt lazily with this size) and the warning limiter."""
    global _POOL, _POOL_SIZE
    with _LOCK:
        old, _POOL = _POOL, None
        _POOL_SIZE = (workers, max_queue)
    if old is not None:
        old.close()
    with _warn_lock:
        _warned.clear()


def _after_fork_in_child() -> None:
    """The child inherits the parent's locks (possibly held) and no worker threads:
    drop the pool so the child lazily builds a fresh one."""
    global _POOL, _LOCK, _warn_lock
    _POOL = None
    _LOCK = threading.Lock()
    _warn_lock = threading.Lock()


if hasattr(os, "register_at_fork"):  # not on Windows
    os.register_at_fork(after_in_child=_after_fork_in_child)
