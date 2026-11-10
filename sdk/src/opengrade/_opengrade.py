"""Public ``Opengrade`` runtime handle and ``current()`` context routing."""

from __future__ import annotations

import asyncio
import logging
import threading
import weakref
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Any

from opengrade import _config, _state
from opengrade._config import DEFAULT_TRACKING_URI, RedactFn, RedactOutputFn, _normalize_uri
from opengrade.async_client import AsyncClient
from opengrade.client import Client
from opengrade.models import ProjectResponse

logger = logging.getLogger("opengrade")

_CURRENT: ContextVar[Opengrade | None] = ContextVar("opengrade_current", default=None)

_INSTANCES: weakref.WeakSet[Opengrade] = weakref.WeakSet()
_INSTANCES_LOCK = threading.Lock()


def _tracking_uri_for_runtime(rt: _state._Runtime) -> str:
    if rt.settings.tracking_uri is not None:
        return _normalize_uri(rt.settings.tracking_uri)
    return DEFAULT_TRACKING_URI


def _api_key_for_runtime(rt: _state._Runtime) -> str | None:
    return rt.settings.api_key or None


def _shared_client_project_id(rt: _state._Runtime) -> str | None:
    """Project id to bind on shared ``client`` / ``async_client()``."""
    return rt.settings.project_id


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
    if og is None:
        raise RuntimeError(
            "No active Opengrade instance. Construct Opengrade(...), use its methods, "
            "or wrap the call in `with og.activate():`."
        )
    return og


def _register_instance(og: Opengrade) -> None:
    with _INSTANCES_LOCK:
        _INSTANCES.add(og)


def _unregister_instance(og: Opengrade) -> None:
    with _INSTANCES_LOCK:
        _INSTANCES.discard(og)


def _all_instances() -> list[Opengrade]:
    with _INSTANCES_LOCK:
        return [og for og in _INSTANCES]


class Opengrade:
    """Configurable opengrade runtime (settings, client, tracing, evaluate)."""

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
        _state.register_runtime(self._runtime)
        self.tracing_enabled = False
        self._activate_token: Token[Opengrade | None] | None = None
        self._instance_id = _otel._next_instance_id()
        _register_instance(self)

    @property
    def settings(self) -> _state.Settings:
        return self._runtime.settings

    @property
    def client(self) -> Client:
        rt = self._runtime
        with rt.client_lock:
            if rt.client is None:
                from opengrade import _context

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
        from opengrade import _context

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

    async def aset_project(self, name: str) -> ProjectResponse | None:
        from opengrade._context import _activate_project, _afind_project, _slugify
        from opengrade._http import OpengradeAPIError, OpengradeError

        cleaned = name.strip()
        if not cleaned:
            raise ValueError("project name must not be empty")
        slug = _slugify(cleaned)
        client = self.async_client()
        try:
            project = await _afind_project(client, cleaned, slug)
            if project is None:
                try:
                    project = await client.projects.create(name=cleaned, slug=slug)
                    logger.info("opengrade created project %r (slug=%s)", cleaned, slug)
                except OpengradeAPIError as exc:
                    if exc.status != 409:
                        raise
                    project = await _afind_project(client, cleaned, slug)
                    if project is None:
                        raise
        except OpengradeError as exc:
            logger.warning("opengrade.aset_project(%r) failed: %s", cleaned, exc)
            return None
        return _activate_project(project, cleaned, self._runtime)

    def get_project(self) -> ProjectResponse | None:
        return self._runtime.active_project

    def configure_capture(
        self,
        *,
        max_capture_bytes: int | None | Any = _config._UNSET,
        redact: RedactFn | None | Any = _config._UNSET,
        redact_output: RedactOutputFn | None | Any = _config._UNSET,
    ) -> None:
        _config.configure_capture(
            self._runtime,
            max_capture_bytes=max_capture_bytes,
            redact=redact,
            redact_output=redact_output,
        )

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

        return _otel.flush(timeout_millis=timeout_millis, runtime=self._runtime)

    def close(self) -> None:
        from opengrade._context import _close_runtime_clients

        _close_runtime_clients(self._runtime)
        _unregister_instance(self)

    def log_score(self, *args: Any, **kwargs: Any) -> bool:
        with self.activate():
            from opengrade import feedback

            return feedback.log_score(*args, **kwargs)

    def log_feedback(self, *args: Any, **kwargs: Any) -> bool:
        with self.activate():
            from opengrade import feedback

            return feedback.log_feedback(*args, **kwargs)

    def score_trace(self, *args: Any, **kwargs: Any) -> bool:
        with self.activate():
            from opengrade import feedback

            return feedback.score_trace(*args, **kwargs)

    def start_experiment(self, *args: Any, **kwargs: Any) -> Any:
        with self.activate():
            from opengrade.experiment import start_experiment

            kwargs.setdefault("client", self.client)
            return start_experiment(*args, **kwargs)

    def evaluate(self, *args: Any, **kwargs: Any) -> Any:
        with self.activate():
            from opengrade.experiment import evaluate

            kwargs.setdefault("client", self.client)
            return evaluate(*args, **kwargs)

    def sweep(self, *args: Any, **kwargs: Any) -> Any:
        with self.activate():
            from opengrade.sweeps import sweep

            kwargs.setdefault("client", self.client)
            return sweep(*args, **kwargs)

    def evaluate_retrieval(self, *args: Any, **kwargs: Any) -> Any:
        with self.activate():
            from opengrade.retrieval import evaluate_retrieval

            kwargs.setdefault("client", self.client)
            return evaluate_retrieval(*args, **kwargs)

    def log_params(self, **params: Any) -> dict[str, Any]:
        with self.activate():
            from opengrade.experiment import log_params

            return log_params(**params)

    def log_metrics(self, metrics: Mapping[str, float]) -> dict[str, float]:
        with self.activate():
            from opengrade.experiment import log_metrics

            return log_metrics(metrics)

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
