"""Experiment-level scalar metrics (MLflow-style ``log_metrics``): one final value per key."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from typing import Any

METRIC_KEY_PATTERN = re.compile(r"[A-Za-z0-9_.\-/]{1,200}")
MAX_METRICS_PER_REQUEST = 1000


def validate_experiment_metrics(metrics: Mapping[str, Any]) -> dict[str, float]:
    """Return ``metrics`` as ``{key: float}``.

    Raises ValueError on an empty map, a key outside ``[A-Za-z0-9_.-/]{1,200}``, or a
    value that is not a finite int/float (booleans are rejected).
    """
    if not metrics:
        raise ValueError("metrics must not be empty")
    if len(metrics) > MAX_METRICS_PER_REQUEST:
        raise ValueError(f"at most {MAX_METRICS_PER_REQUEST} metrics per request")
    cleaned: dict[str, float] = {}
    for key, value in metrics.items():
        if not isinstance(key, str) or not METRIC_KEY_PATTERN.fullmatch(key):
            raise ValueError(f"invalid metric key {key!r}: use 1-200 letters, digits or _ . - /")
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError(f"metric {key!r} must be a number, got {value!r}")
        try:
            number = float(value)
        except OverflowError:
            raise ValueError(f"metric {key!r} must be finite") from None
        if not math.isfinite(number):
            raise ValueError(f"metric {key!r} must be finite")
        cleaned[key] = number
    return cleaned
