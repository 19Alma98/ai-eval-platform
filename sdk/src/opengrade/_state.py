"""Process-wide default runtime: settings overrides, clients, tracing, metrics, scores."""

from __future__ import annotations

import asyncio
import os
import threading
import weakref
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from opengrade.async_client import AsyncClient
    from opengrade.client import Client
    from opengrade.models import ProjectResponse
    from opentelemetry.sdk.trace import SpanProcessor, TracerProvider


@dataclass(frozen=True, slots=True)
class Settings:
    tracking_uri: str | None = None
    api_key: str | None = None
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
        fields = cls.__dataclass_fields__
        kwargs = {k: v for k, v in overrides.items() if k in fields}
        return cls(**kwargs)

    def with_updates(self, **kwargs: Any) -> Settings:
        fields = self.__class__.__dataclass_fields__
        clean = {k: v for k, v in kwargs.items() if k in fields}
        return replace(self, **clean)


@dataclass
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

    @classmethod
    def fresh(cls) -> _Runtime:
        # Matches opengrade._production MAX_WORKERS / MAX_QUEUE defaults.
        return cls(pool_size=(2, 1000))

    def reset_config_overrides(self) -> None:
        self.settings = Settings.from_env()

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


_MISSING = object()

_DEFAULT: _Runtime | None = None
_DEFAULT_LOCK = threading.Lock()


def _module_override(module: str, name: str) -> Any:
    """Pytest contract: ``monkeypatch.setattr(mod, NAME, …)`` writes into
    ``sys.modules[mod].__dict__``. Prefer that shadow over ``_Runtime`` so
    existing tests keep working without rewriting every fixture."""
    import sys

    mod = sys.modules.get(module)
    if mod is not None and name in mod.__dict__:
        return mod.__dict__[name]
    return _MISSING


def _default() -> _Runtime:
    global _DEFAULT
    with _DEFAULT_LOCK:
        if _DEFAULT is None:
            _DEFAULT = _Runtime.fresh()
        return _DEFAULT


def _set_default(runtime: _Runtime) -> None:
    global _DEFAULT
    with _DEFAULT_LOCK:
        _DEFAULT = runtime


def _reset_default_for_tests() -> _Runtime:
    global _DEFAULT
    with _DEFAULT_LOCK:
        _DEFAULT = _Runtime.fresh()
        return _DEFAULT


def _after_fork_in_child() -> None:
    _default().after_fork_in_child()


def _tracking_uri_override() -> str | None:
    value = _module_override("opengrade._config", "_TRACKING_URI")
    if value is not _MISSING:
        return value
    return _default().settings.tracking_uri


def _set_tracking_uri_override(value: str | None) -> None:
    rt = _default()
    rt.settings = rt.settings.with_updates(tracking_uri=value)


def _api_key_override() -> str | None:
    value = _module_override("opengrade._config", "_API_KEY")
    if value is not _MISSING:
        return value
    return _default().settings.api_key


def _set_api_key_override(value: str | None) -> None:
    rt = _default()
    rt.settings = rt.settings.with_updates(api_key=value)


def _active_project_id() -> str | None:
    value = _module_override("opengrade._config", "_ACTIVE_PROJECT_ID")
    if value is not _MISSING:
        return value
    return _default().settings.project_id


def _active_project_slug() -> str | None:
    value = _module_override("opengrade._config", "_ACTIVE_PROJECT_SLUG")
    if value is not _MISSING:
        return value
    return _default().settings.project_slug


def _set_active_project(
    *,
    project_id: str | None = None,
    project_slug: str | None = None,
) -> None:
    rt = _default()
    updates: dict[str, Any] = {}
    if project_id is not None:
        updates["project_id"] = project_id
    if project_slug is not None:
        updates["project_slug"] = project_slug
    if updates:
        rt.settings = rt.settings.with_updates(**updates)


def _max_capture_override() -> int | None:
    value = _module_override("opengrade._config", "_MAX_CAPTURE_BYTES")
    if value is not _MISSING:
        return value
    return _default().settings.max_capture_bytes


def _set_max_capture_override(value: int | None) -> None:
    rt = _default()
    rt.settings = rt.settings.with_updates(max_capture_bytes=value)


def _warned_plaintext_key() -> bool:
    value = _module_override("opengrade._config", "_WARNED_PLAINTEXT_KEY")
    if value is not _MISSING:
        return value
    return _default().settings.warned_plaintext_key


def _set_warned_plaintext_key(value: bool) -> None:
    rt = _default()
    rt.settings = rt.settings.with_updates(warned_plaintext_key=value)


if hasattr(os, "register_at_fork"):  # not on Windows
    os.register_at_fork(after_in_child=_after_fork_in_child)
