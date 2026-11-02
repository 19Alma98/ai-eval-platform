"""Trace-level attributes: user, session, tags and metadata.

They use the OpenInference semantic conventions so the platform (and any other
OpenInference backend) reads them the same way auto-instrumented spans write them:

- ``user.id`` / ``session.id``: strings
- ``tag.tags``: list of strings
- ``metadata``: JSON object serialised as a string

The platform lifts them from any span of a trace onto the trace itself, so setting
them on a nested span is enough. ``using_attributes`` scopes them to a block: every
span opengrade opens inside the block carries them (and, when the OpenInference
instrumentation package is installed, so do auto-instrumented LLM spans).
"""

from __future__ import annotations

import contextlib
import json
import logging
from collections.abc import Iterable, Iterator, Mapping
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from typing import Any

from opentelemetry import trace as otel_trace
from opentelemetry.trace import Span

logger = logging.getLogger("opengrade")

USER_ID_ATTR = "user.id"
SESSION_ID_ATTR = "session.id"
TAGS_ATTR = "tag.tags"
METADATA_ATTR = "metadata"

MAX_ID_CHARS = 200
MAX_TAG_CHARS = 200
MAX_TAGS = 50
MAX_METADATA_KEYS = 50
MAX_METADATA_VALUE_CHARS = 500


@dataclass(frozen=True, slots=True)
class _Scoped:
    user_id: str | None = None
    session_id: str | None = None
    tags: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


_SCOPED: ContextVar[_Scoped | None] = ContextVar("opengrade_trace_attrs", default=None)


def _clean_id(value: object, what: str) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        logger.warning("opengrade: empty %s ignored", what)
        return None
    return text[:MAX_ID_CHARS]


def _clean_tags(tags: Iterable[object]) -> tuple[str, ...]:
    out: list[str] = []
    for tag in tags:
        if tag is None:
            continue
        text = str(tag).strip()[:MAX_TAG_CHARS]
        if text and text not in out:
            out.append(text)
    return tuple(out)


def _clean_value(value: object) -> str | int | float | bool | None:
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return value[:MAX_METADATA_VALUE_CHARS]
    try:
        text = json.dumps(value, default=str)
    except Exception:  # noqa: BLE001 — never break the caller
        text = str(value)
    return text[:MAX_METADATA_VALUE_CHARS]


def _clean_metadata(metadata: Mapping[str, object]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in metadata.items():
        name = str(key).strip()
        if not name or name.startswith("_"):
            logger.warning("opengrade: metadata key %r ignored (empty or starts with '_')", key)
            continue
        out[name[:MAX_ID_CHARS]] = _clean_value(value)
    return out


def _merge_tags(existing: Iterable[str], new: Iterable[str]) -> tuple[str, ...]:
    merged = list(existing)
    for tag in new:
        if tag not in merged:
            merged.append(tag)
    if len(merged) > MAX_TAGS:
        logger.warning("opengrade: more than %d tags on a trace; extra tags dropped", MAX_TAGS)
    return tuple(merged[:MAX_TAGS])


def _merge_metadata(existing: Mapping[str, Any], new: Mapping[str, Any]) -> dict[str, Any]:
    merged = {**existing, **new}
    if len(merged) > MAX_METADATA_KEYS:
        logger.warning(
            "opengrade: more than %d metadata keys on a trace; extra keys dropped",
            MAX_METADATA_KEYS,
        )
        merged = dict(list(merged.items())[:MAX_METADATA_KEYS])
    return merged


def _span_attr(span: Span, key: str) -> Any:
    attrs = getattr(span, "attributes", None)
    if not attrs:
        return None
    try:
        return attrs.get(key)
    except Exception:  # noqa: BLE001
        return None


def _span_tags(span: Span) -> tuple[str, ...]:
    value = _span_attr(span, TAGS_ATTR)
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list | tuple):
        return tuple(str(v) for v in value)
    return ()


def _span_metadata(span: Span) -> dict[str, Any]:
    value = _span_attr(span, METADATA_ATTR)
    if not isinstance(value, str):
        return {}
    try:
        parsed = json.loads(value)
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _write(
    span: Span,
    *,
    user_id: str | None = None,
    session_id: str | None = None,
    tags: tuple[str, ...] = (),
    metadata: Mapping[str, Any] | None = None,
) -> None:
    if not span.is_recording():
        return
    if user_id is not None:
        span.set_attribute(USER_ID_ATTR, user_id)
    if session_id is not None:
        span.set_attribute(SESSION_ID_ATTR, session_id)
    if tags:
        span.set_attribute(TAGS_ATTR, list(_merge_tags(_span_tags(span), tags)))
    if metadata:
        merged = _merge_metadata(_span_metadata(span), metadata)
        span.set_attribute(METADATA_ATTR, json.dumps(merged, default=str))


def apply_scoped(span: Span) -> None:
    """Stamp the attributes of the enclosing ``using_attributes`` blocks on a new span."""
    scoped = _SCOPED.get()
    if scoped is None:
        return
    _write(
        span,
        user_id=scoped.user_id,
        session_id=scoped.session_id,
        tags=scoped.tags,
        metadata=scoped.metadata,
    )


def _current() -> Span | None:
    span = otel_trace.get_current_span()
    if not span.is_recording():
        logger.debug("opengrade: no active span; trace attribute ignored")
        return None
    return span


def set_user(user_id: str | None) -> None:
    """Set the end user (``user.id``) of the current trace.

    Call it inside a traced call (``@opengrade.trace`` or ``opengrade.span``); the
    platform lifts it to the trace, so any span of the trace works. No-op otherwise.
    """
    span = _current()
    cleaned = _clean_id(user_id, "user id")
    if span is not None and cleaned is not None:
        _write(span, user_id=cleaned)


def set_session(session_id: str | None) -> None:
    """Set the session / conversation (``session.id``) of the current trace."""
    span = _current()
    cleaned = _clean_id(session_id, "session id")
    if span is not None and cleaned is not None:
        _write(span, session_id=cleaned)


def set_tags(*tags: str) -> None:
    """Add tags (``tag.tags``) to the current trace; repeated calls accumulate."""
    span = _current()
    cleaned = _clean_tags(tags)
    if span is not None and cleaned:
        _write(span, tags=cleaned)


def set_metadata(metadata: Mapping[str, object] | None = None, **kwargs: object) -> None:
    """Merge key/value metadata (``metadata``) into the current trace.

    Values should be scalars (str, int, float, bool); anything else is stored as
    JSON text. Keys starting with ``_`` are reserved and ignored. Traces can be
    filtered by ``key:value`` in the UI and API.
    """
    span = _current()
    merged: dict[str, object] = dict(metadata or {})
    merged.update(kwargs)
    cleaned = _clean_metadata(merged)
    if span is not None and cleaned:
        _write(span, metadata=cleaned)


@contextlib.contextmanager
def using_attributes(
    *,
    user_id: str | None = None,
    session_id: str | None = None,
    tags: Iterable[str] | None = None,
    metadata: Mapping[str, object] | None = None,
) -> Iterator[None]:
    """Attach user / session / tags / metadata to every span opened in this block.

    Blocks nest: inner ids win, tags and metadata accumulate. Useful in a request
    middleware, where the user is known before any traced call starts::

        with opengrade.using_attributes(user_id=user.id, session_id=chat_id, tags=["beta"]):
            answer(question)
    """
    parent = _SCOPED.get() or _Scoped()
    scoped = replace(
        parent,
        user_id=_clean_id(user_id, "user id") or parent.user_id,
        session_id=_clean_id(session_id, "session id") or parent.session_id,
        tags=_merge_tags(parent.tags, _clean_tags(tags or ())),
        metadata=_merge_metadata(parent.metadata, _clean_metadata(metadata or {})),
    )
    token = _SCOPED.set(scoped)
    try:
        with _openinference_attributes(scoped):
            yield
    finally:
        _SCOPED.reset(token)


@contextlib.contextmanager
def _openinference_attributes(scoped: _Scoped) -> Iterator[None]:
    """Propagate to auto-instrumented spans when OpenInference is installed."""
    try:
        from openinference.instrumentation import using_attributes as oi_using_attributes
    except Exception:  # noqa: BLE001 — optional dependency
        yield
        return
    kwargs: dict[str, Any] = {}
    if scoped.user_id is not None:
        kwargs["user_id"] = scoped.user_id
    if scoped.session_id is not None:
        kwargs["session_id"] = scoped.session_id
    if scoped.tags:
        kwargs["tags"] = list(scoped.tags)
    if scoped.metadata:
        kwargs["metadata"] = dict(scoped.metadata)
    try:
        cm = oi_using_attributes(**kwargs)
        cm.__enter__()
    except Exception:  # noqa: BLE001 — never break the caller
        yield
        return
    try:
        yield
    finally:
        with contextlib.suppress(Exception):
            cm.__exit__(None, None, None)
