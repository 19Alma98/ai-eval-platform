"""Public ``Opengrade`` runtime handle and ``current()`` context routing."""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Any

from opengrade import _config, _context, _state
from opengrade._config import DEFAULT_TRACKING_URI, _normalize_uri
from opengrade.async_client import AsyncClient
from opengrade.client import Client
from opengrade.models import ProjectResponse

logger = logging.getLogger("opengrade")

_CURRENT: ContextVar[Opengrade | None] = ContextVar("opengrade_current", default=None)

_DEFAULT_OPENGRADE: Opengrade | None = None
_DEFAULT_OPENGRADE_LOCK = threading.Lock()


def _tracking_uri_for_runtime(rt: _state._Runtime) -> str:
    if rt.settings.tracking_uri is not None:
        return _normalize_uri(rt.settings.tracking_uri)
    if rt is _state._default():
        return _config.get_tracking_uri()
    value = os.getenv("OPENGRADE_TRACKING_URI")
    if value and value.strip():
        return _normalize_uri(value)
    return DEFAULT_TRACKING_URI


def _api_key_for_runtime(rt: _state._Runtime) -> str | None:
    if rt.settings.api_key is not None:
        return rt.settings.api_key or None
    if rt is _state._default():
        return _config.get_api_key()
    value = (os.getenv("OPENGRADE_API_KEY") or "").strip()
    return value or None


def _shared_client_project_id(rt: _state._Runtime) -> str | None:
    """Project id to bind on shared ``get_client()`` / ``async_client()``.

    Settings / ``set_project`` first; on the process default runtime, also
    ``OPENGRADE_PROJECT_ID``. Bare ``Client()`` does not use this helper.
    """
    if rt.settings.project_id:
        return rt.settings.project_id
    if rt is not _state._default():
        return rt.settings.project_id
    active = _state._active_project_id()
    if active:
        return active
    env_id = os.getenv("OPENGRADE_PROJECT_ID")
    if env_id and env_id.strip():
        return env_id.strip()
    return None


def _ensure_client_project_id(client: Client | AsyncClient, rt: _state._Runtime) -> None:
    if client._project_id is None:
        pid = _shared_client_project_id(rt)
        if pid is not None:
            client._project_id = pid


def active_runtime() -> _state._Runtime:
    """Runtime backing ``current()`` (for internal subsystems at call time)."""
    return current()._runtime


def current() -> Opengrade:
    og = _CURRENT.get()
    if og is not None:
        return og
    return _default_opengrade()


def _default_opengrade() -> Opengrade:
    global _DEFAULT_OPENGRADE
    with _DEFAULT_OPENGRADE_LOCK:
        if _DEFAULT_OPENGRADE is None:
            _DEFAULT_OPENGRADE = Opengrade._wrap_default(_state._default())
        return _DEFAULT_OPENGRADE


def _reset_opengrade_for_tests() -> None:
    global _DEFAULT_OPENGRADE
    _CURRENT.set(None)
    with _DEFAULT_OPENGRADE_LOCK:
        _DEFAULT_OPENGRADE = None


class Opengrade:
    """Configurable opengrade runtime (settings, client, tracing flags)."""

    __slots__ = ("_runtime", "tracing_enabled", "_activate_token", "_instance_id", "__weakref__")

    def __init__(self, settings: _state.Settings | None = None, **kwargs: Any) -> None:
        fields = _state.Settings.__dataclass_fields__
        if settings is None:
            settings = _state.Settings.from_env(**{k: v for k, v in kwargs.items() if k in fields})
        elif kwargs:
            settings = settings.with_updates(**{k: v for k, v in kwargs.items() if k in fields})
        from opengrade import _otel

        self._runtime = _state._Runtime.fresh()
        self._runtime.settings = settings
        self.tracing_enabled = False
        self._activate_token: Token[Opengrade | None] | None = None
        self._instance_id = _otel._next_instance_id()

    @classmethod
    def _wrap_default(cls, rt: _state._Runtime) -> Opengrade:
        og = cls.__new__(cls)
        from opengrade import _otel

        og._runtime = rt
        og.tracing_enabled = bool(rt.initialized)
        og._activate_token = None
        og._instance_id = _otel._next_instance_id()
        return og

    @property
    def settings(self) -> _state.Settings:
        return self._runtime.settings

    @property
    def client(self) -> Client:
        rt = self._runtime
        with rt.client_lock:
            if rt.client is None:
                rt.client = _context.Client(
                    _tracking_uri_for_runtime(rt),
                    api_key=_api_key_for_runtime(rt),
                    project_id=_shared_client_project_id(rt),
                )
            else:
                _ensure_client_project_id(rt.client, rt)
            return rt.client

    def async_client(self) -> AsyncClient:
        rt = self._runtime
        uri = _tracking_uri_for_runtime(rt)
        api_key = _api_key_for_runtime(rt)
        project_id = _shared_client_project_id(rt)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            with rt.client_lock:
                if rt.async_client_no_loop is None:
                    rt.async_client_no_loop = _context.AsyncClient(
                        uri, api_key=api_key, project_id=project_id
                    )
                else:
                    _ensure_client_project_id(rt.async_client_no_loop, rt)
                return rt.async_client_no_loop
        with rt.client_lock:
            client = rt.async_clients.get(loop)
            if client is None:
                client = _context.AsyncClient(uri, api_key=api_key, project_id=project_id)
                rt.async_clients[loop] = client
            else:
                _ensure_client_project_id(client, rt)
            return client

    def set_project(self, name: str) -> ProjectResponse | None:
        from opengrade._context import resolve_or_create_project

        return resolve_or_create_project(name, self.client, activate=True, runtime=self._runtime)

    def init_tracing(self, **kwargs: Any) -> None:
        """Configure OTLP export for this instance via the shared ``TracerProvider``."""
        from opengrade import _otel

        _otel.init_for_instance(self, **kwargs)

    @property
    def trace(self) -> Any:
        from opengrade._trace import trace

        return trace

    def flush(self, timeout_millis: int = 5000) -> bool:
        from opengrade import _otel

        return _otel.flush(timeout_millis=timeout_millis)

    def close(self) -> None:
        from opengrade._context import _close_runtime_clients

        _close_runtime_clients(self._runtime)

    @contextmanager
    def activate(self) -> Iterator[Opengrade]:
        token = _CURRENT.set(self)
        try:
            yield self
        finally:
            _CURRENT.reset(token)

    def __enter__(self) -> Opengrade:
        self._activate_token = _CURRENT.set(self)
        return self

    def __exit__(self, *_exc: object) -> None:
        if self._activate_token is not None:
            _CURRENT.reset(self._activate_token)
            self._activate_token = None
        self.close()
