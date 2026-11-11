"""Background sender for trace scores: never blocks or raises into user code."""

from __future__ import annotations

import atexit
import json
import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from typing import Any, cast

from opengrade import _state
from opengrade._errors import OpengradeAPIError

logger = logging.getLogger("opengrade")

Post = Callable[[str, list[dict[str, Any]]], object]

MAX_QUEUE = 10_000
BATCH_SIZE = 100
BATCH_MAX_BYTES = 512 * 1024  # half the server's 1 MiB body limit
FLUSH_INTERVAL_S = 2.0
RETRY_BACKOFF_S = 1.0
EXIT_FLUSH_TIMEOUT_S = 5.0
_DROP_WARNING_EVERY_S = 60.0


def _default_post(project_id: str, scores: list[dict[str, Any]]) -> None:
    from opengrade._opengrade import current  # lazy: avoids import cycles

    current().client.trace_scores.log(project_id, scores)


def _runtime_post(rt: _state._Runtime) -> Post:
    """Post through ``rt``'s own client.

    The sender thread has no activated instance, so ``current()`` would raise there
    and every score would be dropped.
    """

    def post(project_id: str, scores: list[dict[str, Any]]) -> None:
        from opengrade._opengrade import client_for_runtime  # lazy: avoids import cycles

        client_for_runtime(rt).trace_scores.log(project_id, scores)

    return post


def _size(score: dict[str, Any]) -> int:
    return len(json.dumps(score, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


class ScoreSender:
    def __init__(
        self,
        post: Post = _default_post,
        *,
        max_queue: int = MAX_QUEUE,
        batch_size: int = BATCH_SIZE,
        interval: float = FLUSH_INTERVAL_S,
        retry_backoff: float = RETRY_BACKOFF_S,
    ) -> None:
        self._post = post
        self._max_queue = max_queue
        self._batch_size = batch_size
        self._interval = interval
        self._retry_backoff = retry_backoff
        self._queue: deque[tuple[str, dict[str, Any]]] = deque()
        self._cond = threading.Condition()
        self._in_flight = 0
        self._flush_requested = False
        self._thread: threading.Thread | None = None
        self._last_drop_warning: float | None = None
        self._last_send_warning: float | None = None
        self.dropped = 0

    def enqueue(self, project_id: str, score: dict[str, Any]) -> bool:
        with self._cond:
            if len(self._queue) >= self._max_queue:
                self.dropped += 1
                now = time.monotonic()
                if (
                    self._last_drop_warning is None
                    or now - self._last_drop_warning >= _DROP_WARNING_EVERY_S
                ):
                    self._last_drop_warning = now
                    logger.warning(
                        "opengrade: score queue full (%d); dropping trace scores", self._max_queue
                    )
                return False
            self._queue.append((project_id, score))
            self._ensure_thread()  # on failure the item stays queued
            if len(self._queue) >= self._batch_size:
                self._cond.notify_all()
            return True

    def flush(self, timeout: float = 5.0) -> bool:
        """Send everything queued; False when ``timeout`` expired first."""
        deadline = time.monotonic() + timeout
        with self._cond:
            if not self._queue and self._in_flight == 0:
                return True
            if not self._ensure_thread():
                return False
            self._flush_requested = True
            self._cond.notify_all()
            while self._queue or self._in_flight:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._cond.wait(remaining)
            return True

    def _ensure_thread(self) -> bool:  # caller holds the lock
        if self._thread is not None and self._thread.is_alive():
            return True
        try:
            thread = threading.Thread(target=self._run, name="opengrade-scores", daemon=True)
            thread.start()
        except RuntimeError as exc:  # out of threads / interpreter shutting down
            logger.debug("opengrade: could not start score sender thread: %s", exc)
            self._thread = None
            return False
        self._thread = thread
        return True

    def _run(self) -> None:
        while True:
            with self._cond:
                if len(self._queue) < self._batch_size and not self._flush_requested:
                    self._cond.wait(self._interval)
                if not self._queue:
                    self._flush_requested = False
                    self._cond.notify_all()
                    continue
                batch: list[tuple[str, dict[str, Any]]] = []
                budget = 0
                while self._queue and len(batch) < self._batch_size:
                    size = _size(self._queue[0][1])
                    if batch and budget + size > BATCH_MAX_BYTES:
                        break
                    budget += size
                    batch.append(self._queue.popleft())
                count = len(batch)
                self._in_flight = count
                if not self._queue:
                    self._flush_requested = False
            try:
                self._send(batch)
            finally:
                with self._cond:
                    self._in_flight = 0
                    self._cond.notify_all()

    def _send(self, batch: list[tuple[str, dict[str, Any]]]) -> None:
        by_project: dict[str, list[dict[str, Any]]] = {}
        for project_id, score in batch:
            by_project.setdefault(project_id, []).append(score)
        for project_id, scores in by_project.items():
            self._send_project(project_id, scores)

    def _send_project(self, project_id: str, scores: list[dict[str, Any]]) -> None:
        for attempt in (1, 2):
            try:
                self._post(project_id, scores)
                return
            except Exception as exc:  # noqa: BLE001 — sending must never crash the thread
                if isinstance(exc, OpengradeAPIError) and exc.status == 413:
                    if len(scores) > 1:
                        mid = len(scores) // 2
                        self._send_project(project_id, scores[:mid])
                        self._send_project(project_id, scores[mid:])
                    else:
                        self._drop(project_id, 1, exc)
                    return
                if isinstance(exc, OpengradeAPIError) and 400 <= exc.status < 500:
                    # The server rejects a whole batch for one bad item: retrying cannot
                    # help, so resend each item once to salvage the valid ones.
                    # Only validation errors (400/422) are per-item; 401/403/404 etc.
                    # would fail every item, so drop the whole batch at once.
                    if len(scores) > 1 and exc.status in (400, 422):
                        self._resend_individually(project_id, scores, exc)
                    else:
                        self._drop(project_id, len(scores), exc)
                    return
                if attempt == 2:
                    self._drop(project_id, len(scores), exc)
                elif self._retry_backoff > 0:
                    time.sleep(self._retry_backoff)

    def _resend_individually(
        self, project_id: str, scores: list[dict[str, Any]], batch_error: Exception
    ) -> None:
        failed = 0
        last_error = batch_error
        for score in scores:
            try:
                self._post(project_id, [score])
            except Exception as exc:  # noqa: BLE001
                failed += 1
                last_error = exc
        if failed:
            self._drop(project_id, failed, last_error)

    def _drop(self, project_id: str, count: int, exc: Exception) -> None:
        detail = exc.detail if isinstance(exc, OpengradeAPIError) and exc.detail else exc
        message = "opengrade: dropped %d trace scores for project %s: %s"
        with self._cond:
            self.dropped += count
            now = time.monotonic()
            loud = (
                self._last_send_warning is None
                or now - self._last_send_warning >= _DROP_WARNING_EVERY_S
            )
            if loud:
                self._last_send_warning = now
        logger.log(logging.WARNING if loud else logging.DEBUG, message, count, project_id, detail)


_PROCESS_EXIT_DEADLINE: float | None = None


def _exit_deadline() -> float | None:
    value = _state._module_override("opengrade._scores", "_EXIT_DEADLINE")
    if value is not _state._MISSING:
        return cast(float | None, value)
    return _PROCESS_EXIT_DEADLINE


def _set_exit_deadline(value: float | None) -> None:
    global _PROCESS_EXIT_DEADLINE
    import sys

    if _state._module_override("opengrade._scores", "_EXIT_DEADLINE") is not _state._MISSING:
        sys.modules["opengrade._scores"].__dict__["_EXIT_DEADLINE"] = value
    else:
        _PROCESS_EXIT_DEADLINE = value
        for rt in _state.iter_runtimes():
            rt.exit_deadline = value


def exit_remaining() -> float:
    """Seconds left of the one ``EXIT_FLUSH_TIMEOUT_S`` budget all exit handlers share."""
    now = time.monotonic()
    deadline = _exit_deadline()
    if deadline is None:
        deadline = now + EXIT_FLUSH_TIMEOUT_S
        _set_exit_deadline(deadline)
    return max(0.0, deadline - now)


def _at_exit() -> None:
    try:
        flush(exit_remaining())
    except Exception:  # noqa: BLE001 — never raise during interpreter shutdown
        logger.debug("opengrade: score flush at exit failed", exc_info=True)


def sender(runtime: _state._Runtime | None = None) -> ScoreSender:
    rt = runtime if runtime is not None else _state.active_runtime()
    with rt.scores_lock:
        if rt.score_sender is None:
            rt.score_sender = ScoreSender(_runtime_post(rt))
        if not rt.scores_atexit_registered:
            atexit.register(_at_exit)
            rt.scores_atexit_registered = True
        return rt.score_sender


def enqueue(
    project_id: str, score: dict[str, Any], *, runtime: _state._Runtime | None = None
) -> bool:
    return sender(runtime).enqueue(project_id, score)


def flush(timeout: float = 5.0, *, runtime: _state._Runtime | None = None) -> bool:
    runtimes = [runtime] if runtime is not None else _state.iter_runtimes()
    ok = True
    for rt in runtimes:
        current = rt.score_sender
        if current is not None:
            ok = current.flush(timeout) and ok
    return ok


_SCORES_MODULE_STATE_KEYS = ("_SENDER", "_LOCK", "_ATEXIT_REGISTERED", "_EXIT_DEADLINE")


def _clear_module_state_keys() -> None:
    import sys

    mod = sys.modules[__name__]
    for key in _SCORES_MODULE_STATE_KEYS:
        mod.__dict__.pop(key, None)


def _after_fork_in_child() -> None:
    """The child inherits the parent's lock/condition (possibly held) and no thread:
    drop senders so the child lazily builds fresh ones."""
    for rt in _state.iter_runtimes():
        rt.score_sender = None
        rt.scores_lock = threading.Lock()
    _set_exit_deadline(None)


def __getattr__(name: str) -> Any:
    if name == "_EXIT_DEADLINE":
        return _PROCESS_EXIT_DEADLINE
    try:
        rt = _state.active_runtime()
    except RuntimeError:
        rt = None
    if name == "_SENDER":
        return None if rt is None else rt.score_sender
    if name == "_LOCK":
        return None if rt is None else rt.scores_lock
    if name == "_ATEXIT_REGISTERED":
        return False if rt is None else rt.scores_atexit_registered
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
