"""Public ``Opengrade`` runtime handle and ``current()`` context routing."""

from __future__ import annotations

import asyncio
import functools
import inspect
import logging
import threading
import weakref
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from contextvars import ContextVar, Token
from typing import TYPE_CHECKING, Any, Literal

from opengrade import _config, _state, _trace_attrs
from opengrade import _trace as _trace_mod
from opengrade._config import DEFAULT_TRACKING_URI, RedactFn, RedactOutputFn, _normalize_uri
from opengrade.async_client import AsyncClient
from opengrade.client import Client
from opengrade.models import ProjectResponse

if TYPE_CHECKING:
    from opengrade.experiment.result import ExperimentResult
    from opengrade.experiment.runtime import Experiment
    from opengrade.metrics import LocalMetric, Sample
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


def client_for_runtime(rt: _state._Runtime) -> Client:
    """Shared sync ``Client`` of ``rt`` (created on first use).

    Background threads (score sender) use this instead of ``current().client``: a
    ``ContextVar`` set by ``activate()`` is not visible in a thread they did not start from.
    """
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


def ambient() -> Opengrade | None:
    """Instance tracing should use here: the active one, else the sole tracing instance.

    ``ContextVar`` values do not reach threads started without ``copy_context()`` (plain
    ``ThreadPoolExecutor``, library-owned threads). With a single traced instance in the
    process there is no ambiguity, so tracing there still lands in that instance. With
    several, nothing is guessed and the caller gets None.
    """
    og = _CURRENT.get()
    if og is not None:
        return og
    with _INSTANCES_LOCK:
        traced = [inst for inst in _INSTANCES if inst.tracing_enabled]
    return traced[0] if len(traced) == 1 else None


def default_instance() -> Opengrade:
    """Instance for a call that names none: the active one, else the only one alive."""
    og = _CURRENT.get()
    if og is not None:
        return og
    instances = _all_instances()
    if len(instances) == 1:
        return instances[0]
    return current()  # raises with the usual hint


def _register_instance(og: Opengrade) -> None:
    with _INSTANCES_LOCK:
        _INSTANCES.add(og)


def _unregister_instance(og: Opengrade) -> None:
    with _INSTANCES_LOCK:
        _INSTANCES.discard(og)


def _all_instances() -> list[Opengrade]:
    with _INSTANCES_LOCK:
        return [og for og in _INSTANCES]


def _bind_traced(og: Opengrade, traced: Callable[..., Any]) -> Callable[..., Any]:
    """Run ``traced`` (an ``opengrade.trace`` wrapper) with ``og`` as the current instance.

    Generators are advanced one step at a time inside the scope, so ``og`` is never left
    active in the consumer's code between two items.
    """
    target = traced
    while isinstance(target, functools.partial):
        target = target.func

    if inspect.isasyncgenfunction(target):

        @functools.wraps(traced)
        async def bound_agen(*args: Any, **kwargs: Any) -> Any:
            og._ensure_tracing()
            agen = traced(*args, **kwargs)
            try:
                while True:
                    token = _CURRENT.set(og)
                    try:
                        item = await agen.__anext__()
                    except StopAsyncIteration:
                        return
                    finally:
                        _CURRENT.reset(token)
                    yield item
            finally:
                token = _CURRENT.set(og)
                try:
                    await agen.aclose()
                finally:
                    _CURRENT.reset(token)

        return bound_agen

    if inspect.isgeneratorfunction(target):

        @functools.wraps(traced)
        def bound_gen(*args: Any, **kwargs: Any) -> Any:
            og._ensure_tracing()
            gen = traced(*args, **kwargs)
            try:
                while True:
                    token = _CURRENT.set(og)
                    try:
                        item = next(gen)
                    except StopIteration:
                        return
                    finally:
                        _CURRENT.reset(token)
                    yield item
            finally:
                token = _CURRENT.set(og)
                try:
                    gen.close()
                finally:
                    _CURRENT.reset(token)

        return bound_gen

    if inspect.iscoroutinefunction(target):

        @functools.wraps(traced)
        async def bound_async(*args: Any, **kwargs: Any) -> Any:
            og._ensure_tracing()
            token = _CURRENT.set(og)
            try:
                return await traced(*args, **kwargs)
            finally:
                _CURRENT.reset(token)

        return bound_async

    @functools.wraps(traced)
    def bound(*args: Any, **kwargs: Any) -> Any:
        og._ensure_tracing()
        token = _CURRENT.set(og)
        try:
            return traced(*args, **kwargs)
        finally:
            _CURRENT.reset(token)

    return bound


class _BoundSpan(_trace_mod.span):
    """``opengrade.span`` routed to one instance for the duration of the block."""

    __slots__ = ("_og", "_token")

    def __init__(self, og: Opengrade, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._og = og
        self._token: Token[Opengrade | None] | None = None

    def __enter__(self) -> _trace_mod.SpanHandle:
        self._og._ensure_tracing()
        self._token = _CURRENT.set(self._og)
        try:
            return super().__enter__()
        except BaseException:
            self._reset()
            raise

    def __exit__(self, exc_type: Any, exc: BaseException | None, tb: Any) -> None:
        try:
            super().__exit__(exc_type, exc, tb)
        finally:
            self._reset()

    def _reset(self) -> None:
        token, self._token = self._token, None
        if token is not None:
            try:
                _CURRENT.reset(token)
            except ValueError:  # exited in another context (e.g. a different task)
                pass


class Opengrade:
    """Configurable opengrade runtime (settings, client, tracing, evaluate)."""

    __slots__ = (
        "_runtime",
        "tracing_enabled",
        "_activate_token",
        "_instance_id",
        "_auto_init_done",
        "_wants_tracing",
        "_auto_init_lock",
        "__weakref__",
    )

    def __init__(self, settings: _state.Settings | None = None, **kwargs: Any) -> None:
        """``Opengrade(project="my-app")`` is enough: the rest comes from ``OPENGRADE_*``.

        ``project`` is a name, created on the platform if missing. ``project_id`` /
        ``project_slug`` point at an existing project instead. Any other ``Settings``
        field can be passed as a keyword.
        """
        _state.check_setting_names(kwargs, where="Opengrade()")
        if settings is None:
            settings = _state.Settings.from_env(**kwargs)
        elif kwargs:
            settings = settings.with_updates(**kwargs)
        if settings.project and not settings.project_id and not settings.project_slug:
            from opengrade._context import _slugify

            settings = settings.with_updates(project_slug=_slugify(settings.project))
        from opengrade import _otel

        self._auto_init_done = False
        self._wants_tracing = False  # set once anything is decorated with og.trace / og.span
        self._auto_init_lock = threading.Lock()

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
        client = client_for_runtime(rt)
        if rt.settings.project and not rt.settings.project_id:
            from opengrade._context import ensure_project

            ensure_project(rt, client)  # find or create; quiet when unreachable
        return client

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

    # --- tracing -----------------------------------------------------------------------

    def _ensure_tracing(self) -> None:
        """Start tracing with defaults the first time ``og.trace`` / ``og.span`` runs."""
        if self._auto_init_done or self._runtime.initialized:
            return
        with self._auto_init_lock:
            if self._auto_init_done:
                return
            self._auto_init_done = True  # one attempt: init logs its own failure
            if not self._runtime.initialized:
                self.init_tracing()

    def trace(self, name: Any = None, **options: Any) -> Any:
        """Trace a function in this instance's project: ``@og.trace`` or ``@og.trace(...)``.

        Same options as ``opengrade.trace`` (``name``, ``kind``, ``metrics``, ``redact``,
        ...). Unlike it, the call is routed to this instance without ``activate()``, and
        tracing starts by itself (``init_tracing()`` defaults) if it was not initialized.
        """
        from opengrade._trace import trace as _trace

        self._wants_tracing = True
        if callable(name) and not options:
            return _bind_traced(self, _trace(name))
        decorate: Callable[[Callable[..., Any]], Callable[..., Any]] = _trace(name, **options)

        def bind(fn: Callable[..., Any]) -> Callable[..., Any]:
            return _bind_traced(self, decorate(fn))

        return bind

    def span(
        self,
        name: str,
        kind: str = "CHAIN",
        *,
        input: object = None,  # noqa: A002 — mirrors OpenInference ``input.value``
        attributes: dict[str, object] | None = None,
        live: bool | None = None,
    ) -> _trace_mod.span:
        """Trace a block as a span of this instance (``with`` or ``async with``)."""
        self._wants_tracing = True
        return _BoundSpan(self, name, kind, input=input, attributes=attributes, live=live)

    def set_input(self, value: object) -> None:
        """Set the input shown for the current span."""
        _trace_mod.set_input(value)

    def set_output(self, value: object) -> None:
        """Set the output shown for the current span."""
        _trace_mod.set_output(value)

    def set_attribute(self, key: str, value: object) -> None:
        _trace_mod.set_attribute(key, value)

    def set_attributes(self, attrs: dict[str, object] | None = None, **kwargs: object) -> None:
        _trace_mod.set_attributes(attrs, **kwargs)

    def set_error(self, description: str, *, exception: BaseException | None = None) -> None:
        """Mark the current span as failed without raising."""
        _trace_mod.set_error(description, exception=exception)

    def current_trace_id(self) -> str | None:
        """Id of the trace in progress (what feedback and scores attach to)."""
        return _trace_mod.current_trace_id()

    def set_user(self, user_id: str) -> None:
        _trace_attrs.set_user(user_id)

    def set_session(self, session_id: str) -> None:
        _trace_attrs.set_session(session_id)

    def set_tags(self, *tags: Any) -> None:
        _trace_attrs.set_tags(*tags)

    def set_metadata(self, metadata: Mapping[str, Any] | None = None, **kwargs: Any) -> None:
        _trace_attrs.set_metadata(metadata, **kwargs)

    def using_attributes(
        self,
        *,
        user_id: str | None = None,
        session_id: str | None = None,
        tags: Iterable[str] | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> AbstractContextManager[None]:
        """Context manager: user / session / tags / metadata for every span in the block."""
        return _trace_attrs.using_attributes(
            user_id=user_id, session_id=session_id, tags=tags, metadata=metadata
        )

    def set_retrieval_documents(self, documents: Iterable[object]) -> None:
        """Record the retrieved documents (dicts or objects with an ``id``)."""
        from opengrade._eval_run import set_retrieval_documents

        set_retrieval_documents(documents)

    def set_search_query(self, query: str) -> None:
        from opengrade._eval_run import set_search_query

        set_search_query(query)

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

    def start_experiment(self, *args: Any, **kwargs: Any) -> Experiment:
        with self.activate():
            from opengrade.experiment import start_experiment as impl

            return impl(*args, **kwargs)

    def evaluate(self, *args: Any, **kwargs: Any) -> ExperimentResult:
        with self.activate():
            from opengrade.experiment import evaluate as impl

            return impl(*args, **kwargs)

    def sweep(self, *args: Any, **kwargs: Any) -> SweepResult:
        with self.activate():
            from opengrade.sweeps import sweep as impl

            return impl(*args, **kwargs)

    def evaluate_retrieval(self, *args: Any, **kwargs: Any) -> ExperimentResult:
        with self.activate():
            from opengrade.retrieval import evaluate_retrieval as impl

            return impl(*args, **kwargs)

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


def _attach_delegate_signature(method: Any, target: Callable[..., Any]) -> None:
    """Give ``Opengrade`` thin delegates the concrete signature of ``target`` (+ ``self``)."""
    target_sig = inspect.signature(target)
    self_param = inspect.Parameter("self", inspect.Parameter.POSITIONAL_OR_KEYWORD)
    method.__signature__ = target_sig.replace(
        parameters=(self_param, *target_sig.parameters.values())
    )
    method.__doc__ = target.__doc__


def _attach_experiment_delegate_signatures() -> None:
    from opengrade.experiment.api import evaluate as evaluate_fn
    from opengrade.experiment.api import start_experiment as start_experiment_fn
    from opengrade.retrieval import evaluate_retrieval as evaluate_retrieval_fn
    from opengrade.sweeps import sweep as sweep_fn

    _attach_delegate_signature(Opengrade.start_experiment, start_experiment_fn)
    _attach_delegate_signature(Opengrade.evaluate, evaluate_fn)
    _attach_delegate_signature(Opengrade.sweep, sweep_fn)
    _attach_delegate_signature(Opengrade.evaluate_retrieval, evaluate_retrieval_fn)


_attach_experiment_delegate_signatures()
