"""Production scores and end-user feedback attached to a trace.

Calls never raise and never block: invalid input or a missing trace/project logs a
warning and returns False; valid scores are queued for the background sender.
"""

from __future__ import annotations

import json
import logging
import math
import numbers
import re
import threading
import time
from collections.abc import Callable, Mapping
from decimal import Decimal
from typing import Any

from opengrade import _config, _scores, _trace
from opengrade.metrics import LocalMetric, Sample, Score, evaluate_metric, missing_requirement

logger = logging.getLogger("opengrade")

FEEDBACK_NAME = "user_feedback"
_LABELS = frozenset({"PASS", "FAIL", "ERROR", "SKIPPED"})
_TRACE_ID = re.compile(r"[0-9a-f]{32}")
_MAX_TEXT = 4000
_MAX_AUTHOR = 200


def _number(field_name: str, value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if not isinstance(value, numbers.Real | Decimal):
        raise ValueError(f"{field_name} must be a number, got {value!r}")
    try:
        number = float(value)
    except (OverflowError, ArithmeticError):
        raise ValueError(f"{field_name} is out of range") from None
    if not math.isfinite(number):
        raise ValueError(f"{field_name} must be finite, got {number}")
    return number


def _text(field_name: str, value: str) -> str:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError(f"{field_name} is not valid UTF-8 text (lone surrogate)") from None
    return value


def _trace_id(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError(f"trace_id must be a string, got {value!r}")
    normalized = value.strip().lower()
    if not _TRACE_ID.fullmatch(normalized):
        raise ValueError(f"trace_id must be 32 hex characters, got {value!r}")
    return normalized


_MAX_METADATA_BYTES = 16_384


def _metadata(metadata: Any) -> dict[str, Any]:
    if not isinstance(metadata, Mapping):
        raise ValueError(f"metadata must be a mapping, got {type(metadata).__name__}")
    try:
        dumped = json.dumps(dict(metadata), default=str, allow_nan=False, ensure_ascii=False)
    except ValueError as exc:  # NaN/Infinity, circular reference
        raise ValueError(f"metadata is not valid JSON: {exc}") from None
    _text("metadata", dumped)
    result = json.loads(dumped)
    assert isinstance(result, dict)
    # Same serialization the server measures, so the cap matches its 422.
    size = len(json.dumps(result, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    if size > _MAX_METADATA_BYTES:
        raise ValueError(f"metadata is {size} bytes serialized, the limit is {_MAX_METADATA_BYTES}")
    return result


def _payload(
    name: str,
    value: Any,
    *,
    source: str,
    label: str | None = None,
    explanation: str | None = None,
    threshold: Any = None,
    author: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    cleaned = name.strip() if isinstance(name, str) else ""
    if not cleaned or len(cleaned) > 200:
        raise ValueError(f"score name must be 1-200 characters, got {name!r}")
    _text("name", cleaned)
    payload: dict[str, Any] = {"name": cleaned, "value": _number("value", value), "source": source}
    if label is not None and not isinstance(label, str):
        raise ValueError(f"label must be a string, got {label!r}")
    if label is not None and label.strip():
        upper = label.strip().upper()
        if upper not in _LABELS:
            raise ValueError(f"label must be one of {sorted(_LABELS)}, got {label!r}")
        payload["label"] = upper
    if threshold is not None:
        payload["threshold"] = _number("threshold", threshold)
    if explanation is not None:
        payload["explanation"] = _text("explanation", str(explanation)[:_MAX_TEXT])
    if author is not None and str(author).strip():
        payload["author"] = _text("author", str(author).strip()[:_MAX_AUTHOR])
    if metadata is not None:
        cleaned_metadata = _metadata(metadata)
        if cleaned_metadata:
            payload["metadata"] = cleaned_metadata
    return payload


_WARN_EVERY_S = 60.0
_config_warned: dict[str, float] = {}
_config_lock = threading.Lock()


class _ConfigError(ValueError):
    """Setup problem (no project / no trace), not a bad argument: warned at most once a minute."""

    def __init__(self, category: str, message: str) -> None:
        super().__init__(message)
        self.category = category


def _reset_for_tests() -> None:
    with _config_lock:
        _config_warned.clear()


def _warn_config(category: str, what: str, message: str) -> None:
    now = time.monotonic()
    with _config_lock:
        last = _config_warned.get(category)
        loud = last is None or now - last >= _WARN_EVERY_S
        if loud:
            _config_warned[category] = now
    logger.log(
        logging.WARNING if loud else logging.DEBUG, "opengrade: %s ignored: %s", what, message
    )


def _describe(exc: BaseException) -> str:
    try:
        return f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
    except Exception:  # noqa: BLE001 — a hostile __str__ must not escape
        return type(exc).__name__


def error_score(exc: BaseException) -> Score:
    """Score for a raising or timed-out metric (same shape as experiment ERROR rows)."""
    return Score(label="ERROR", explanation=_describe(exc)[:_MAX_TEXT])


def _name_for_log(name: Any) -> str:
    return repr(name) if isinstance(name, str) else type(name).__name__


def _guarded(what: str, action: Callable[[], bool]) -> bool:
    """Run ``action``; any failure is logged (no traceback) and turned into False."""
    try:
        return action()
    except _ConfigError as exc:
        _warn_config(exc.category, what, str(exc))
    except (TypeError, ValueError) as exc:
        logger.warning("opengrade: %s ignored: %s", what, _describe(exc))
    except Exception as exc:  # noqa: BLE001 — scoring must never break the caller
        logger.warning("opengrade: %s ignored: %s", what, _describe(exc))
    return False


def _queue(what: str, trace_id: str | None, build: Callable[[], dict[str, Any]]) -> bool:
    """Resolve trace + project, build the payload, enqueue; warn and return False on any problem."""
    from opengrade._otel import is_disabled

    if is_disabled():
        return False

    def action() -> bool:
        resolved = trace_id if trace_id is not None else _trace.current_trace_id()
        if resolved is None:
            raise _ConfigError("trace", "no trace_id and no active trace")
        normalized = _trace_id(resolved)
        try:
            project_id = _config.resolve_project_id()
        except ValueError as exc:
            raise _ConfigError("project", str(exc)) from None
        payload = build()
        return _scores.enqueue(project_id, {"trace_id": normalized, **payload})

    return _guarded(what, action)


def _metric_payload(metric: LocalMetric, result: Score) -> dict[str, Any]:
    return _payload(
        metric.name or "",
        result.value,
        source="sdk",
        label=result.label,
        explanation=result.explanation,
        threshold=metric.threshold,
        metadata=result.metadata,
    )


def _feedback_value(positive: Any) -> float:
    if isinstance(positive, bool) or (isinstance(positive, int) and positive in (0, 1)):
        return 1.0 if positive else 0.0
    raise ValueError(f"positive must be a bool (or 0/1), got {type(positive).__name__}")


def log_score(
    name: str,
    value: float | bool | None,
    *,
    trace_id: str | None = None,
    label: str | None = None,
    explanation: str | None = None,
    threshold: float | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> bool:
    """Queue a score for a trace (default: the current one). False when not queued.

    The platform sets PASS/FAIL with the same rule as experiment metrics: an explicit
    ``label`` FAIL/ERROR/SKIPPED wins, a value under ``threshold`` fails, otherwise
    0 fails and anything else passes.
    """
    return _queue(
        f"log_score({_name_for_log(name)})",
        trace_id,
        lambda: _payload(
            name,
            value,
            source="sdk",
            label=label,
            explanation=explanation,
            threshold=threshold,
            metadata=metadata,
        ),
    )


def log_feedback(
    positive: bool,
    *,
    trace_id: str | None = None,
    comment: str | None = None,
    user_id: str | None = None,
) -> bool:
    """Record an end-user thumbs up/down on a trace (``user_feedback``, 1 or 0).

    One value per (trace, user): a user changing their mind replaces the old value.
    Without ``user_id`` the feedback is anonymous and shares one row per trace
    (the last write wins).
    """
    return _queue(
        "log_feedback",
        trace_id,
        lambda: _payload(
            FEEDBACK_NAME,
            _feedback_value(positive),
            source="human",
            explanation=comment,
            author=user_id,
        ),
    )


def queue_metric_score(project_id: str, trace_id: str, metric: LocalMetric, result: Score) -> bool:
    """Queue one metric result computed for ``trace_id`` (used by production metrics)."""

    def action() -> bool:
        if not metric.name:
            raise ValueError("the metric needs a name")
        normalized = _trace_id(trace_id)
        payload = _metric_payload(metric, result)
        return _scores.enqueue(project_id, {"trace_id": normalized, **payload})

    return _guarded(f"metric {_name_for_log(getattr(metric, 'name', None))} result", action)


def score_trace(metric: LocalMetric, sample: Sample, *, trace_id: str | None = None) -> bool:
    """Run ``metric`` on ``sample`` now and queue the result for the trace.

    Trace: ``trace_id``, else ``sample.trace_id``, else the current trace. A metric
    whose ``requires`` are not met is skipped (False). A raising metric logs a
    warning and queues ``label="ERROR"`` with the exception as explanation (True
    when that score is queued).
    """

    def action() -> bool:
        if not isinstance(metric, LocalMetric) or not metric.name:
            raise ValueError("the metric needs a name (use @opengrade.metric)")
        if not isinstance(sample, Sample):
            raise ValueError(f"sample must be an opengrade.Sample, got {type(sample).__name__}")
        missing = missing_requirement(sample, metric.requires)
        if missing is not None:
            logger.debug("opengrade: metric %s skipped: missing %s", metric.name, missing)
            return False
        try:
            result = evaluate_metric(metric, sample)
        except Exception as exc:  # noqa: BLE001 — a broken metric must not break the caller
            logger.warning("opengrade: metric %s failed: %s", metric.name, _describe(exc))
            result = error_score(exc)
        return _queue(
            f"score_trace({_name_for_log(metric.name)})",
            trace_id if trace_id is not None else sample.trace_id,
            lambda: _metric_payload(metric, result),
        )

    return _guarded("score_trace()", action)
