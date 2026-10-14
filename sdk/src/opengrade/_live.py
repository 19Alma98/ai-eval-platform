"""Production live interactions derived from ``@opengrade.trace`` spans.

The outermost traced call outside an experiment is marked ``opengrade.live=true``;
the platform turns that span into a live interaction at OTLP ingestion. Only a
``sample_rate`` fraction is sent to the judge (``opengrade.live.judge``), decided
from the trace id so every span of a trace agrees.
"""

from __future__ import annotations

import logging
import os
from contextvars import ContextVar, Token

from opentelemetry.trace import Span

from opengrade._run_context import ACTIVE_RUN

logger = logging.getLogger("opengrade")

LIVE_ATTR = "opengrade.live"
LIVE_JUDGE_ATTR = "opengrade.live.judge"
LIVE_SAMPLE_RATE_ATTR = "opengrade.live.sample_rate"

_TRUTHY = frozenset({"1", "true", "yes", "on"})
_TRACE_ID_LOW_BITS = (1 << 64) - 1

_ENABLED: bool | None = None
_SAMPLE_RATE: float | None = None

# True while inside a live-marked span: nested traced calls are part of it.
_IN_LIVE: ContextVar[bool] = ContextVar("aiobs_in_live", default=False)


def _parse_rate(value: object) -> float:
    rate = float(value)  # type: ignore[arg-type]
    if not 0.0 <= rate <= 1.0:
        raise ValueError(f"live_sample_rate must be within [0, 1], got {rate}")
    return rate


def configure(*, enabled: bool | None = None, sample_rate: float | None = None) -> None:
    """Set live capture from ``init()``; None falls back to the env vars."""
    global _ENABLED, _SAMPLE_RATE
    _ENABLED = enabled
    _SAMPLE_RATE = None if sample_rate is None else _parse_rate(sample_rate)


def _reset_for_tests() -> None:
    configure()


def is_enabled() -> bool:
    """``init(live=...)`` > ``OPENGRADE_LIVE`` > off."""
    if _ENABLED is not None:
        return _ENABLED
    return os.getenv("OPENGRADE_LIVE", "").strip().lower() in _TRUTHY


def sample_rate() -> float:
    """``init(live_sample_rate=...)`` > ``OPENGRADE_LIVE_SAMPLE_RATE`` > 1.0."""
    if _SAMPLE_RATE is not None:
        return _SAMPLE_RATE
    raw = os.getenv("OPENGRADE_LIVE_SAMPLE_RATE", "").strip()
    if not raw:
        return 1.0
    try:
        return _parse_rate(raw)
    except ValueError:
        logger.warning("opengrade: invalid OPENGRADE_LIVE_SAMPLE_RATE=%r; judging every interaction", raw)
        return 1.0


def should_judge(trace_id: int, rate: float) -> bool:
    """Deterministic per trace (same rule as OTEL ``TraceIdRatioBased``)."""
    if rate >= 1.0:
        return True
    if rate <= 0.0:
        return False
    return (trace_id & _TRACE_ID_LOW_BITS) < round(rate * (_TRACE_ID_LOW_BITS + 1))


def mark_if_live(span: Span, live: bool | None) -> Token[bool] | None:
    """Mark ``span`` as a live interaction when it is the outermost production call.

    Returns a token to pass to ``unmark`` (None when the span was not marked).
    """
    if live is False or _IN_LIVE.get() or ACTIVE_RUN.get() is not None:
        return None
    if live is None and not is_enabled():
        return None
    if not span.is_recording():
        return None
    ctx = span.get_span_context()
    rate = sample_rate()
    span.set_attribute(LIVE_ATTR, True)
    span.set_attribute(LIVE_SAMPLE_RATE_ATTR, rate)
    span.set_attribute(LIVE_JUDGE_ATTR, should_judge(ctx.trace_id, rate))
    return _IN_LIVE.set(True)


def unmark(token: Token[bool] | None) -> None:
    if token is not None:
        _IN_LIVE.reset(token)
