"""Reset SDK module state between tests (not part of the public package)."""

from __future__ import annotations

from typing import Any


def reset_sdk(*, otel: bool = True, scores_post: Any | None = ..., **score_kwargs: Any) -> None:
    """Drop clients, runtimes, pools/senders, and optional global OTEL router state.

    Pass ``scores_post`` (and optional ScoreSender kwargs) to inject a test sender
    on every registered runtime; omit to clear senders until next use.
    """
    from opengrade import _live, _otel, _production, _scores, _state, feedback
    from opengrade._context import _close_runtime_clients
    from opengrade._opengrade import _CURRENT, _INSTANCES, _INSTANCES_LOCK

    if otel:
        _otel._clear_module_state_keys()
        from opengrade.instrumentation import deactivate_instrumentors

        deactivate_instrumentors()
        _otel._shutdown_and_reset_global_tracer_provider()
        _otel._INSTANCE_ID_COUNTER = 0
        _otel._PROCESS_ATEXIT_REGISTERED = False

    # Close HTTP clients for every live Opengrade handle.
    from opengrade._opengrade import _all_instances

    for og in _all_instances():
        _close_runtime_clients(og._runtime)

    for rt in _state.iter_runtimes():
        _live.configure(enabled=None, sample_rate=None, runtime=rt)
        rt.reset_live_overrides()
        with rt.production_pool_lock:
            old, rt.pool = rt.pool, None
            rt.metrics_workers = None
            rt.pool_size = (_production.MAX_WORKERS, _production.MAX_QUEUE)
        if old is not None:
            old.close()
        with rt.production_warn_lock:
            rt.production_warned.clear()
        with rt.scores_lock:
            if scores_post is not ...:
                rt.score_sender = (
                    _scores.ScoreSender(scores_post, **score_kwargs)
                    if scores_post is not None
                    else None
                )
            else:
                rt.score_sender = None
            rt.exit_deadline = None
        rt.initialized = False
        if otel:
            from opengrade._config import configure_capture

            configure_capture(rt)

    _scores._clear_module_state_keys()
    _scores._PROCESS_EXIT_DEADLINE = None
    with feedback._config_lock:
        feedback._config_warned.clear()

    _CURRENT.set(None)
    with _INSTANCES_LOCK:
        _INSTANCES.clear()
    with _state._RUNTIMES_LOCK:
        _state._RUNTIMES.clear()


def reset_production(*, workers: int | None = None, max_queue: int | None = None) -> None:
    """Drop metric pools on registered runtimes (rebuilt lazily)."""
    from opengrade import _production, _state

    w = workers if workers is not None else _production.MAX_WORKERS
    q = max_queue if max_queue is not None else _production.MAX_QUEUE
    for rt in _state.iter_runtimes():
        with rt.production_pool_lock:
            old, rt.pool = rt.pool, None
            rt.metrics_workers = None
            rt.pool_size = (w, q)
        if old is not None:
            old.close()
        with rt.production_warn_lock:
            rt.production_warned.clear()


def reset_scores(post: Any | None = None, **kwargs: Any) -> Any:
    """Replace score senders on registered runtimes (``post=None`` → lazy recreate)."""
    from opengrade import _scores, _state

    _scores._clear_module_state_keys()
    _scores._PROCESS_EXIT_DEADLINE = None
    last = None
    for rt in _state.iter_runtimes():
        with rt.scores_lock:
            rt.score_sender = _scores.ScoreSender(post, **kwargs) if post is not None else None
            rt.exit_deadline = None
            last = rt.score_sender
    return last
