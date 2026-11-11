"""Per-instance runtime: settings, clients, tracing, metrics, scores."""

from __future__ import annotations

import asyncio
import difflib
import os
import threading
import weakref
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from opentelemetry.sdk.trace import SpanProcessor, TracerProvider

    from opengrade.async_client import AsyncClient
    from opengrade.client import Client
    from opengrade.models import ProjectResponse


@dataclass(frozen=True, slots=True)
class Settings:
    tracking_uri: str | None = None
    api_key: str | None = None
    # Project by name, created on the platform if missing. ``project_id`` /
    # ``project_slug`` instead point at a project that must already exist.
    project: str | None = None
    project_id: str | None = None
    project_slug: str | None = None
    service_name: str | None = None
    version: str | None = None
    environment: str | None = None
    live: bool | None = None
    live_sample_rate: float | None = None
    metrics_workers: int | None = None
    max_capture_bytes: int | None = None
    warned_plaintext_key: bool = False

    @classmethod
    def from_env(cls, **overrides: Any) -> Settings:
        """Build settings from ``OPENGRADE_*`` env vars, then apply ``overrides``."""
        kwargs: dict[str, Any] = {}
        env_map = {
            "tracking_uri": "OPENGRADE_TRACKING_URI",
            "api_key": "OPENGRADE_API_KEY",
            "project": "OPENGRADE_PROJECT",
            "project_id": "OPENGRADE_PROJECT_ID",
            "project_slug": "OPENGRADE_PROJECT_SLUG",
            "service_name": "OPENGRADE_SERVICE_NAME",
            "version": "OPENGRADE_VERSION",
            "environment": "OPENGRADE_ENVIRONMENT",
        }
        for field_name, env_name in env_map.items():
            raw = os.getenv(env_name)
            if raw is not None and raw.strip():
                kwargs[field_name] = raw.strip()
        live_raw = os.getenv("OPENGRADE_LIVE", "").strip().lower()
        if live_raw in {"1", "true", "yes", "on"}:
            kwargs["live"] = True
        elif live_raw in {"0", "false", "no", "off"}:
            kwargs["live"] = False
        rate_raw = os.getenv("OPENGRADE_LIVE_SAMPLE_RATE", "").strip()
        if rate_raw:
            try:
                kwargs["live_sample_rate"] = float(rate_raw)
            except ValueError:
                pass
        workers_raw = os.getenv("OPENGRADE_METRICS_WORKERS", "").strip()
        if workers_raw:
            try:
                kwargs["metrics_workers"] = int(workers_raw, 10)
            except ValueError:
                pass
        cap_raw = os.getenv("OPENGRADE_MAX_CAPTURE_BYTES", "").strip()
        if cap_raw:
            try:
                kwargs["max_capture_bytes"] = int(cap_raw, 10)
            except ValueError:
                pass
        check_setting_names(overrides, where="Settings.from_env()")
        kwargs.update(overrides)
        return cls(**kwargs)

    def with_updates(self, **kwargs: Any) -> Settings:
        check_setting_names(kwargs, where="Settings.with_updates()")
        return replace(self, **kwargs)


def check_setting_names(names: Any, *, where: str) -> None:
    """Raise ``TypeError`` for keys that are not ``Settings`` fields (catches typos)."""
    fields = Settings.__dataclass_fields__
    unknown = sorted(k for k in names if k not in fields)
    if not unknown:
        return
    hints = []
    for name in unknown:
        close = difflib.get_close_matches(name, list(fields), n=1)
        hints.append(f"{name!r}" + (f" (did you mean {close[0]!r}?)" if close else ""))
    raise TypeError(f"{where} got unexpected setting(s): {', '.join(hints)}")


@dataclass(eq=False)
class _Runtime:
    settings: Settings = field(default_factory=Settings)

    client_lock: threading.Lock = field(default_factory=threading.Lock)
    client: Client | None = None
    async_clients: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, AsyncClient] = field(
        default_factory=weakref.WeakKeyDictionary
    )
    async_client_no_loop: AsyncClient | None = None
    active_project: ProjectResponse | None = None

    provider: TracerProvider | None = None
    processor: SpanProcessor | None = None
    exporter: Any | None = None
    owns_provider: bool = False
    initialized: bool = False
    otel_atexit_registered: bool = False

    live_enabled: bool | None = None
    live_sample_rate: float | None = None

    metrics_workers: int | None = None
    pool: Any | None = None
    pool_size: tuple[int, int] | None = None
    production_pool_lock: threading.Lock = field(default_factory=threading.Lock)
    production_atexit_registered: bool = False
    production_warned: dict[str, float] = field(default_factory=dict)
    production_warn_lock: threading.Lock = field(default_factory=threading.Lock)

    score_sender: Any | None = None
    scores_lock: threading.Lock = field(default_factory=threading.Lock)
    scores_atexit_registered: bool = False
    exit_deadline: float | None = None

    capture_redact: Any | None = None
    capture_redact_output: Any | None = None

    slug_not_found: set[str] = field(default_factory=set)
    ensure_project_lock: threading.Lock = field(default_factory=threading.Lock)

    @classmethod
    def fresh(cls) -> _Runtime:
        # Matches opengrade._production MAX_WORKERS / MAX_QUEUE defaults.
        return cls(pool_size=(2, 1000))

    def reset_config_overrides(self) -> None:
        self.settings = Settings.from_env()
        self.capture_redact = None
        self.capture_redact_output = None
        self.slug_not_found.clear()

    def reset_live_overrides(self) -> None:
        self.live_enabled = None
        self.live_sample_rate = None

    def reset_client_refs(self) -> None:
        """Drop client handles without closing (fork child path)."""
        self.client = None
        self.async_client_no_loop = None
        self.async_clients = weakref.WeakKeyDictionary()
        self.client_lock = threading.Lock()

    def after_fork_in_child(self) -> None:
        self.reset_client_refs()
        self.pool = None
        self.production_pool_lock = threading.Lock()
        self.production_warn_lock = threading.Lock()
        self.score_sender = None
        self.scores_lock = threading.Lock()
        self.exit_deadline = None
        self.capture_redact = None
        self.capture_redact_output = None
        self.ensure_project_lock = threading.Lock()


_MISSING = object()

# Weak registry of live runtimes (for fork / optional test sweeps).
_RUNTIMES: weakref.WeakSet[_Runtime] = weakref.WeakSet()
_RUNTIMES_LOCK = threading.Lock()


def register_runtime(rt: _Runtime) -> None:
    with _RUNTIMES_LOCK:
        _RUNTIMES.add(rt)


def iter_runtimes() -> list[_Runtime]:
    with _RUNTIMES_LOCK:
        return list(_RUNTIMES)


def active_runtime() -> _Runtime:
    """Runtime for the activated ``Opengrade``; raises if none is active."""
    from opengrade._opengrade import current

    return current()._runtime


def active_runtime_or_none() -> _Runtime | None:
    """Runtime tracing should use: the activated ``Opengrade``, else the only traced one.

    See ``opengrade._opengrade.ambient``. None when nothing is active and the process
    has zero or several traced instances.
    """
    from opengrade._opengrade import ambient

    og = ambient()
    return None if og is None else og._runtime


def _module_override(module: str, name: str) -> Any:
    """Pytest contract: ``monkeypatch.setattr(mod, NAME, …)`` writes into
    ``sys.modules[mod].__dict__``."""
    import sys

    mod = sys.modules.get(module)
    if mod is not None and name in mod.__dict__:
        return mod.__dict__[name]
    return _MISSING


def _after_fork_in_child() -> None:
    for rt in iter_runtimes():
        rt.after_fork_in_child()


def tracking_uri_for(rt: _Runtime) -> str:
    from opengrade._config import DEFAULT_TRACKING_URI, _normalize_uri

    if rt.settings.tracking_uri is not None:
        return _normalize_uri(rt.settings.tracking_uri)
    return DEFAULT_TRACKING_URI


def api_key_for(rt: _Runtime) -> str | None:
    return rt.settings.api_key or None


def set_active_project(
    rt: _Runtime,
    *,
    project_id: str | None = None,
    project_slug: str | None = None,
) -> None:
    updates: dict[str, Any] = {}
    if project_id is not None:
        updates["project_id"] = project_id
    if project_slug is not None:
        updates["project_slug"] = project_slug
    if updates:
        rt.settings = rt.settings.with_updates(**updates)
        rt.slug_not_found.clear()


def is_slug_not_found(rt: _Runtime, slug: str) -> bool:
    return slug in rt.slug_not_found


def mark_slug_not_found(rt: _Runtime, slug: str) -> None:
    rt.slug_not_found.add(slug)


def clear_slug_not_found(rt: _Runtime) -> None:
    rt.slug_not_found.clear()


# --- legacy aliases used during migration / tests (cycle 2 removes test-only paths) ---


def _set_active_project(
    *,
    project_id: str | None = None,
    project_slug: str | None = None,
) -> None:
    set_active_project(active_runtime(), project_id=project_id, project_slug=project_slug)


def _is_slug_not_found(slug: str) -> bool:
    return is_slug_not_found(active_runtime(), slug)


def _mark_slug_not_found(slug: str) -> None:
    mark_slug_not_found(active_runtime(), slug)


def _clear_slug_not_found() -> None:
    clear_slug_not_found(active_runtime())


def _active_project_id() -> str | None:
    return active_runtime().settings.project_id


def _active_project_slug() -> str | None:
    return active_runtime().settings.project_slug


def _warned_plaintext_key() -> bool:
    return active_runtime().settings.warned_plaintext_key


def _set_warned_plaintext_key(value: bool) -> None:
    rt = active_runtime()
    rt.settings = rt.settings.with_updates(warned_plaintext_key=value)


def _max_capture_override() -> int | None:
    return active_runtime().settings.max_capture_bytes


def _set_max_capture_override(value: int | None) -> None:
    rt = active_runtime()
    rt.settings = rt.settings.with_updates(max_capture_bytes=value)


def _capture_redact() -> Any | None:
    return active_runtime().capture_redact


def _set_capture_redact(value: Any | None) -> None:
    active_runtime().capture_redact = value


def _capture_redact_output() -> Any | None:
    return active_runtime().capture_redact_output


def _set_capture_redact_output(value: Any | None) -> None:
    active_runtime().capture_redact_output = value


if hasattr(os, "register_at_fork"):  # not on Windows
    os.register_at_fork(after_in_child=_after_fork_in_child)
