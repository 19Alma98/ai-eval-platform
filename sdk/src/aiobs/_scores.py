"""Background sender for trace scores: never blocks or raises into user code.

Scores go into a bounded in-memory queue drained by one daemon thread, in batches
every ``interval`` seconds or ``batch_size`` items. A POST that failed on the network
or with a 5xx is retried once, then dropped with a warning; a 4xx is dropped at once
(the server rejects the whole batch and retrying cannot help).
``flush()`` waits (bounded) until the queue is empty.
"""

from __future__ import annotations

import atexit
import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from typing import Any

from aiobs._http import AiobsAPIError

logger = logging.getLogger("aiobs")

Post = Callable[[str, list[dict[str, Any]]], object]

MAX_QUEUE = 10_000
BATCH_SIZE = 100
FLUSH_INTERVAL_S = 2.0
EXIT_FLUSH_TIMEOUT_S = 5.0
_DROP_WARNING_EVERY_S = 60.0


def _default_post(project_id: str, scores: list[dict[str, Any]]) -> None:
    from aiobs._context import get_client  # lazy: _context imports _otel

    get_client().trace_scores.log(project_id, scores)


class ScoreSender:
    def __init__(
        self,
        post: Post = _default_post,
        *,
        max_queue: int = MAX_QUEUE,
        batch_size: int = BATCH_SIZE,
        interval: float = FLUSH_INTERVAL_S,
    ) -> None:
        self._post = post
        self._max_queue = max_queue
        self._batch_size = batch_size
        self._interval = interval
        self._queue: deque[tuple[str, dict[str, Any]]] = deque()
        self._cond = threading.Condition()
        self._in_flight = 0
        self._flush_requested = False
        self._thread: threading.Thread | None = None
        self._last_drop_warning: float | None = None
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
                        "aiobs: score queue full (%d); dropping trace scores", self._max_queue
                    )
                return False
            self._queue.append((project_id, score))
            self._ensure_thread()
            if len(self._queue) >= self._batch_size:
                self._cond.notify_all()
            return True

    def flush(self, timeout: float = 5.0) -> bool:
        """Send everything queued; False when ``timeout`` expired first."""
        deadline = time.monotonic() + timeout
        with self._cond:
            if not self._queue and self._in_flight == 0:
                return True
            self._ensure_thread()
            self._flush_requested = True
            self._cond.notify_all()
            while self._queue or self._in_flight:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._cond.wait(remaining)
            return True

    def _ensure_thread(self) -> None:  # caller holds the lock
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._run, name="aiobs-scores", daemon=True)
            self._thread.start()

    def _run(self) -> None:
        while True:
            with self._cond:
                if len(self._queue) < self._batch_size and not self._flush_requested:
                    self._cond.wait(self._interval)
                if not self._queue:
                    self._flush_requested = False
                    self._cond.notify_all()
                    continue
                count = min(self._batch_size, len(self._queue))
                batch = [self._queue.popleft() for _ in range(count)]
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
            for attempt in (1, 2):
                try:
                    self._post(project_id, scores)
                    break
                except Exception as exc:  # noqa: BLE001 — sending must never crash the thread
                    client_error = isinstance(exc, AiobsAPIError) and 400 <= exc.status < 500
                    if attempt == 2 or client_error:
                        logger.warning(
                            "aiobs: dropped %d trace scores for project %s: %s",
                            len(scores),
                            project_id,
                            exc,
                        )
                        break


_SENDER: ScoreSender | None = None
_LOCK = threading.Lock()
_ATEXIT_REGISTERED = False


def _at_exit() -> None:
    flush(EXIT_FLUSH_TIMEOUT_S)


def sender() -> ScoreSender:
    global _SENDER, _ATEXIT_REGISTERED
    with _LOCK:
        if _SENDER is None:
            _SENDER = ScoreSender()
        if not _ATEXIT_REGISTERED:
            atexit.register(_at_exit)
            _ATEXIT_REGISTERED = True
        return _SENDER


def enqueue(project_id: str, score: dict[str, Any]) -> bool:
    return sender().enqueue(project_id, score)


def flush(timeout: float = 5.0) -> bool:
    current = _SENDER
    return True if current is None else current.flush(timeout)


def _reset_for_tests(post: Post | None = None, **kwargs: Any) -> ScoreSender | None:
    """Replace the shared sender (``post=None`` → none until first use)."""
    global _SENDER
    with _LOCK:
        _SENDER = ScoreSender(post, **kwargs) if post is not None else None
        return _SENDER
