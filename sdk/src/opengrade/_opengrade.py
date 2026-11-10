"""Public ``Opengrade`` runtime handle and ``current()`` context routing."""

from __future__ import annotations

import asyncio
import logging
import threading
import weakref
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import TYPE_CHECKING, Any, Literal

from opengrade import _config, _state
from opengrade._config import DEFAULT_TRACKING_URI, RedactFn, RedactOutputFn, _normalize_uri
from opengrade.async_client import AsyncClient
from opengrade.client import Client
from opengrade.models import ProjectResponse

if TYPE_CHECKING:
    from opengrade.experiment.dataset import DatasetLike
    from opengrade.experiment.result import ExperimentResult
    from opengrade.experiment.runtime import Experiment
    from opengrade.experiment.setup import Metric
    from opengrade.metrics import LocalMetric, Sample
    from opengrade.models import DatasetItemResponse, ExperimentResponse
    from opengrade.sweeps import SweepResult

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

    def init_tracing(
        self,
        *,
        project_id: str | None = None,
        project_slug: str | None = None,
        endpoint: str | None = None,
        service_name: str | None = None,
        instrument: Literal["auto", False] | Sequence[str] = "auto",
        force: bool = False,
        live: bool | None = None,
        live_sample_rate: float | None = None,
        trace_sample_rate: float | None = None,
        max_capture_bytes: int | None = None,
        metrics_workers: int | None = None,
        version: str | None = None,
        environment: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Configure OTLP export for this instance via the shared ``TracerProvider``."""
        from opengrade import _otel

        _otel.init_for_instance(
            self,
            project_id=project_id,
            project_slug=project_slug,
            endpoint=endpoint,
            service_name=service_name,
            instrument=instrument,
            force=force,
            live=live,
            live_sample_rate=live_sample_rate,
            trace_sample_rate=trace_sample_rate,
            max_capture_bytes=max_capture_bytes,
            metrics_workers=metrics_workers,
            version=version,
            environment=environment,
            **kwargs,
        )

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

    def log_score(
        self,
        name: str,
        value: float | bool | None,
        *,
        trace_id: str | None = None,
        label: str | None = None,
        explanation: str | None = None,
        threshold: float | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> bool:
        with self.activate():
            from opengrade import feedback

            return feedback.log_score(
                name,
                value,
                trace_id=trace_id,
                label=label,
                explanation=explanation,
                threshold=threshold,
                metadata=metadata,
            )

    def log_feedback(
        self,
        positive: bool,
        *,
        trace_id: str | None = None,
        comment: str | None = None,
        user_id: str | None = None,
    ) -> bool:
        with self.activate():
            from opengrade import feedback

            return feedback.log_feedback(
                positive,
                trace_id=trace_id,
                comment=comment,
                user_id=user_id,
            )

    def score_trace(
        self,
        metric: LocalMetric,
        sample: Sample,
        *,
        trace_id: str | None = None,
    ) -> bool:
        with self.activate():
            from opengrade import feedback

            return feedback.score_trace(metric, sample, trace_id=trace_id)

    def start_experiment(
        self,
        name: str | None = None,
        *,
        dataset: DatasetLike,
        metrics: Sequence[Metric] | None = None,
        metrics_set_id: str | None = None,
        params: Mapping[str, Any] | None = None,
        baseline: str | ExperimentResponse | ExperimentResult | None = None,
        project: str | None = None,
        version: str | None = None,
        git: bool | Mapping[str, Any] = True,
        task_type: str = "rag_qa",
        app_config_id: str | None = None,
        app_config_alias: str | None = None,
        repeats: int = 1,
        group_by: str | None = None,
        og: Any = None,
        client: Client | None = None,
    ) -> Experiment:
        with self.activate():
            from opengrade.experiment import start_experiment

            return start_experiment(
                name,
                dataset=dataset,
                metrics=metrics,
                metrics_set_id=metrics_set_id,
                params=params,
                baseline=baseline,
                project=project,
                version=version,
                git=git,
                task_type=task_type,
                app_config_id=app_config_id,
                app_config_alias=app_config_alias,
                repeats=repeats,
                group_by=group_by,
                og=og,
                client=self.client if client is None else client,
            )

    def evaluate(
        self,
        *,
        dataset: DatasetLike,
        task: Callable[[DatasetItemResponse], Any],
        metrics: Sequence[Metric] | None = None,
        metrics_set_id: str | None = None,
        name: str | None = None,
        params: Mapping[str, Any] | None = None,
        baseline: str | ExperimentResponse | ExperimentResult | None = None,
        max_concurrency: int = 1,
        project: str | None = None,
        version: str | None = None,
        git: bool | Mapping[str, Any] = True,
        task_type: str = "rag_qa",
        app_config_id: str | None = None,
        app_config_alias: str | None = None,
        raise_on_error: bool = False,
        timeout: float = 600.0,
        repeats: int = 1,
        group_by: str | None = None,
        og: Any = None,
        client: Client | None = None,
    ) -> ExperimentResult:
        with self.activate():
            from opengrade.experiment import evaluate

            return evaluate(
                dataset=dataset,
                task=task,
                metrics=metrics,
                metrics_set_id=metrics_set_id,
                name=name,
                params=params,
                baseline=baseline,
                max_concurrency=max_concurrency,
                project=project,
                version=version,
                git=git,
                task_type=task_type,
                app_config_id=app_config_id,
                app_config_alias=app_config_alias,
                raise_on_error=raise_on_error,
                timeout=timeout,
                repeats=repeats,
                group_by=group_by,
                og=og,
                client=self.client if client is None else client,
            )

    def sweep(
        self,
        *,
        dataset: DatasetLike,
        task: Callable[[DatasetItemResponse, dict[str, Any]], Any] | None = None,
        retriever: Callable[[DatasetItemResponse, dict[str, Any]], Any] | None = None,
        grid: Mapping[str, Sequence[Any]] | None = None,
        variants: Sequence[Mapping[str, Any]] | None = None,
        metrics: Sequence[Metric] | None = None,
        name: str | None = None,
        params: Mapping[str, Any] | None = None,
        baseline: str | ExperimentResponse | ExperimentResult | None = None,
        k: int = 5,
        max_concurrency: int = 1,
        repeats: int = 1,
        group_by: str | None = None,
        project: str | None = None,
        version: str | None = None,
        git: bool | Mapping[str, Any] = True,
        task_type: str = "rag_qa",
        raise_on_error: bool = False,
        timeout: float = 600.0,
        og: Any = None,
        client: Client | None = None,
    ) -> SweepResult:
        with self.activate():
            from opengrade.sweeps import sweep

            return sweep(
                dataset=dataset,
                task=task,
                retriever=retriever,
                grid=grid,
                variants=variants,
                metrics=metrics,
                name=name,
                params=params,
                baseline=baseline,
                k=k,
                max_concurrency=max_concurrency,
                repeats=repeats,
                group_by=group_by,
                project=project,
                version=version,
                git=git,
                task_type=task_type,
                raise_on_error=raise_on_error,
                timeout=timeout,
                og=og,
                client=self.client if client is None else client,
            )

    def evaluate_retrieval(
        self,
        *,
        dataset: DatasetLike,
        retriever: Callable[..., Any],
        k: int = 5,
        metrics: Sequence[Metric] | None = None,
        name: str | None = None,
        params: Mapping[str, Any] | None = None,
        baseline: str | ExperimentResponse | ExperimentResult | None = None,
        max_concurrency: int = 1,
        project: str | None = None,
        version: str | None = None,
        git: bool | Mapping[str, Any] = True,
        doc_id: Callable[[Any], Any] | None = None,
        raise_on_error: bool = False,
        timeout: float = 600.0,
        repeats: int = 1,
        group_by: str | None = None,
        client: Client | None = None,
    ) -> ExperimentResult:
        with self.activate():
            from opengrade.retrieval import evaluate_retrieval

            return evaluate_retrieval(
                dataset=dataset,
                retriever=retriever,
                k=k,
                metrics=metrics,
                name=name,
                params=params,
                baseline=baseline,
                max_concurrency=max_concurrency,
                project=project,
                version=version,
                git=git,
                doc_id=doc_id,
                raise_on_error=raise_on_error,
                timeout=timeout,
                repeats=repeats,
                group_by=group_by,
                client=self.client if client is None else client,
            )

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
