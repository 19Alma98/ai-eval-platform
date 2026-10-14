"""User-defined metrics scored in the user's process (experiments and production)."""

from __future__ import annotations

import inspect
import json
import math
import numbers
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, overload

from opengrade._async import run_sync

LABELS = frozenset({"PASS", "FAIL", "ERROR", "SKIPPED"})
REQUIREMENTS = frozenset({"output", "expected", "documents", "context"})


@dataclass(frozen=True)
class Sample:
    """What a metric sees: one experiment item or one production call.

    In an experiment ``expected`` comes from the dataset item; in production it is
    ``None``. ``documents`` are the retrieved documents (``set_retrieval_documents``).
    """

    input: Any = None
    output: Any = None
    expected: Any = None
    documents: list[dict[str, Any]] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    trace_id: str | None = None
    item_id: str | None = None


@dataclass(frozen=True)
class Score:
    """A metric result. ``label`` overrides the threshold rule only to fail/skip/error."""

    value: float | None = None
    label: str | None = None
    explanation: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def _finite(value: Any) -> float | None:
    if value is None:
        return None
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"metric score must be finite, got {number}")
    return number


def _label(value: Any) -> str | None:
    if value is None or not str(value).strip():
        return None
    label = str(value).strip().upper()
    if label not in LABELS:
        raise ValueError(f"metric label must be one of {sorted(LABELS)}, got {value!r}")
    return label


def _explanation(value: Any) -> str | None:
    return None if value is None else str(value)


def _metadata(value: Mapping[str, Any]) -> dict[str, Any]:
    """Strict-JSON copy (what the platform accepts); NaN/inf or cycles raise ValueError."""
    if not value:
        return {}
    result: dict[str, Any] = json.loads(json.dumps(dict(value), default=str, allow_nan=False))
    return result


def coerce_score(value: Any) -> Score:
    """Normalize what a metric returned into a ``Score``; raises on anything unusable."""
    if isinstance(value, Score):
        return Score(
            _finite(value.value),
            _label(value.label),
            _explanation(value.explanation),
            _metadata(value.metadata),
        )
    if value is None:
        return Score()
    if isinstance(value, bool):
        return Score(1.0 if value else 0.0)
    if isinstance(value, numbers.Real):
        return Score(_finite(value))
    if isinstance(value, Mapping) and "score" in value:
        inner = coerce_score(value["score"])
        return Score(
            inner.value,
            _label(value.get("label", inner.label)),
            _explanation(value.get("explanation", inner.explanation)),
            _metadata(value.get("metadata") or inner.metadata),
        )
    raise TypeError(
        f"metric must return Score, float, bool, None or {{'score': ...}}, got {value!r}"
    )


@dataclass(frozen=True)
class LocalMetric:
    """A Python metric scored in-process, in experiments and in production.

    ``fn(sample)`` gets a ``Sample``; ``fn(item, output)`` (two required positional
    parameters) gets the dataset item and the output. ``fn`` may be ``async``.
    ``threshold`` sets PASS/FAIL (default: 0 fails, anything else passes). Bump
    ``config`` (or ``version`` in ``@opengrade.metric``) when the code changes: compare
    then reports a config mismatch instead of a misleading delta. ``requires`` lists
    ``Sample`` fields that must be non-empty; when one is missing the result is SKIPPED.
    """

    fn: Callable[..., Any]
    name: str | None = None
    threshold: float | None = None
    config: Mapping[str, Any] = field(default_factory=dict)
    requires: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        requires = tuple(self.requires)
        inner = self.fn
        if isinstance(inner, LocalMetric):
            # Re-wrapping (e.g. to change the threshold): keep the inner function so
            # signature detection still sees it, and its requirements. Outer values win.
            object.__setattr__(self, "fn", inner.fn)
            object.__setattr__(self, "name", self.name or inner.name)
            if self.threshold is None:
                object.__setattr__(self, "threshold", inner.threshold)
            object.__setattr__(self, "config", {**inner.config, **self.config})
            requires = tuple(dict.fromkeys(inner.requires + requires))
        object.__setattr__(self, "requires", requires)
        unknown = sorted(set(self.requires) - REQUIREMENTS)
        if unknown:
            raise ValueError(f"unknown requires {unknown}; allowed: {sorted(REQUIREMENTS)}")

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self.fn(*args, **kwargs)


@overload
def metric(fn: Callable[..., Any], /) -> LocalMetric: ...


@overload
def metric(
    *,
    name: str | None = None,
    threshold: float | None = None,
    version: int | str | None = None,
    config: Mapping[str, Any] | None = None,
    requires: Iterable[str] = (),
) -> Callable[[Callable[..., Any]], LocalMetric]: ...


def metric(
    fn: Callable[..., Any] | None = None,
    /,
    *,
    name: str | None = None,
    threshold: float | None = None,
    version: int | str | None = None,
    config: Mapping[str, Any] | None = None,
    requires: Iterable[str] = (),
) -> LocalMetric | Callable[[Callable[..., Any]], LocalMetric]:
    """Turn a function into a ``LocalMetric``.

    ``@opengrade.metric`` or ``@opengrade.metric(threshold=0.5, version=2, requires=("documents",))``.
    ``version`` is stored as ``config["version"]``.
    """

    def wrap(f: Callable[..., Any]) -> LocalMetric:
        merged = dict(config or {})
        if version is not None:
            merged["version"] = version
        default = getattr(f, "__name__", None)
        return LocalMetric(
            f,
            name or (default if default != "<lambda>" else None),
            threshold,
            merged,
            tuple(requires),
        )

    return wrap(fn) if fn is not None else wrap


def missing_requirement(sample: Sample, requires: Iterable[str]) -> str | None:
    """First required ``Sample`` field that is ``None`` or empty, else ``None``."""
    for name in requires:
        value = getattr(sample, name)
        if value is None or (isinstance(value, str | list | dict) and not value):
            return name
    return None


def _takes_item_and_output(fn: Callable[..., Any]) -> bool:
    try:
        params = inspect.signature(fn).parameters.values()
    except (TypeError, ValueError):
        return False
    positional = [
        p
        for p in params
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD) and p.default is p.empty
    ]
    return len(positional) >= 2


def evaluate_metric(
    metric: LocalMetric, sample: Sample, *, item: Any = None, timeout: float | None = None
) -> Score:
    """Run one metric on one sample.

    SKIPPED when a required field is missing. The metric's own exceptions (and an
    unusable return value) propagate: callers record them as ERROR. ``item`` is what
    an ``fn(item, output)`` metric receives; without one it gets the ``Sample``.
    ``timeout`` bounds an async metric (cancelled, ``TimeoutError``); a sync metric
    cannot be interrupted.
    """
    missing = missing_requirement(sample, metric.requires)
    if missing is not None:
        return Score(label="SKIPPED", explanation=f"missing {missing}")
    if _takes_item_and_output(metric.fn):
        raw = metric.fn(item if item is not None else sample, sample.output)
    else:
        raw = metric.fn(sample)
    if inspect.isawaitable(raw):
        raw = run_sync(raw, timeout)
    return coerce_score(raw)
