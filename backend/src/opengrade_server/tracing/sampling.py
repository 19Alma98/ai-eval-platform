"""OTLP head sampling: TraceIdRatioBased-compatible decisions."""

from __future__ import annotations

_TRACE_ID_LOW_BITS = (1 << 64) - 1


def _parse_trace_id(trace_id: int | str) -> int:
    if isinstance(trace_id, int):
        return trace_id
    text = trace_id.strip()
    if text.startswith(("0x", "0X")):
        text = text[2:]
    return int(text, 16)


def should_sample_trace_id(trace_id: int | str, rate: float) -> bool:
    """Deterministic per trace (same rule as OTEL ``TraceIdRatioBased`` / SDK ``should_judge``)."""
    if rate >= 1.0:
        return True
    if rate <= 0.0:
        return False
    tid = _parse_trace_id(trace_id)
    return (tid & _TRACE_ID_LOW_BITS) < round(rate * (_TRACE_ID_LOW_BITS + 1))
