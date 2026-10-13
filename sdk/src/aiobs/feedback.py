"""Production scores and end-user feedback attached to a trace.

Calls never raise and never block: invalid input or a missing trace/project logs a
warning and returns False; valid scores are queued for the background sender.
"""

from __future__ import annotations

import json
import logging
import math
import re
from collections.abc import Mapping
from typing import Any

from aiobs import _config, _scores, _trace
from aiobs.metrics import LocalMetric, Sample, Score, evaluate_metric, missing_requirement

logger = logging.getLogger("aiobs")

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
    if not isinstance(value, int | float):
        raise ValueError(f"{field_name} must be a number, got {value!r}")
    try:
        number = float(value)
    except OverflowError:
        raise ValueError(f"{field_name} is out of range") from None
    if not math.isfinite(number):
        raise ValueError(f"{field_name} must be finite, got {number}")
    return number


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
        payload["explanation"] = str(explanation)[:_MAX_TEXT]
    if author is not None and str(author).strip():
        payload["author"] = str(author).strip()[:_MAX_AUTHOR]
    if metadata:
        payload["metadata"] = json.loads(json.dumps(dict(metadata), default=str))
    return payload


def _queue(what: str, trace_id: str | None, build: Any) -> bool:
    """Resolve trace + project, build the payload, enqueue; warn and return False on any problem."""
    try:
        resolved = trace_id or _trace.current_trace_id()
        if not resolved:
            raise ValueError("no trace_id and no active trace")
        if not isinstance(resolved, str):
            raise ValueError(f"trace_id must be a string, got {resolved!r}")
        normalized = resolved.strip().lower()
        if not _TRACE_ID.fullmatch(normalized):
            raise ValueError(f"trace_id must be 32 hex characters, got {resolved!r}")
        project_id = _config.resolve_project_id()
        payload = build()
    except (TypeError, ValueError) as exc:
        logger.warning("aiobs: %s ignored: %s", what, exc)
        return False
    return _scores.enqueue(project_id, {"trace_id": normalized, **payload})


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
        f"log_score({name!r})",
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
    """
    return _queue(
        "log_feedback",
        trace_id,
        lambda: _payload(
            FEEDBACK_NAME,
            1.0 if positive else 0.0,
            source="human",
            explanation=comment,
            author=user_id,
        ),
    )


def queue_metric_score(project_id: str, trace_id: str, metric: LocalMetric, result: Score) -> bool:
    """Queue one metric result computed for ``trace_id`` (used by production metrics)."""
    assert metric.name is not None
    try:
        payload = _payload(
            metric.name,
            result.value,
            source="sdk",
            label=result.label,
            explanation=result.explanation,
            threshold=metric.threshold,
            metadata=result.metadata,
        )
    except (TypeError, ValueError) as exc:
        logger.warning("aiobs: metric %s result ignored: %s", metric.name, exc)
        return False
    return _scores.enqueue(project_id, {"trace_id": trace_id, **payload})


def score(metric: LocalMetric, sample: Sample, *, trace_id: str | None = None) -> bool:
    """Run ``metric`` on ``sample`` now and queue the result for the trace.

    Trace: ``trace_id``, else ``sample.trace_id``, else the current trace. A metric
    whose ``requires`` are not met is skipped (False). A raising metric logs a
    warning and returns False.
    """
    if not metric.name:
        logger.warning("aiobs: score() ignored: the metric needs a name (use @aiobs.metric)")
        return False
    missing = missing_requirement(sample, metric.requires)
    if missing is not None:
        logger.debug("aiobs: metric %s skipped: missing %s", metric.name, missing)
        return False
    try:
        result = evaluate_metric(metric, sample)
    except Exception as exc:  # noqa: BLE001 — a broken metric must not break the caller
        logger.warning("aiobs: metric %s failed: %s", metric.name, exc)
        return False
    return _queue(
        f"score({metric.name!r})",
        trace_id or sample.trace_id,
        lambda: _payload(
            metric.name or "",
            result.value,
            source="sdk",
            label=result.label,
            explanation=result.explanation,
            threshold=metric.threshold,
            metadata=result.metadata,
        ),
    )
