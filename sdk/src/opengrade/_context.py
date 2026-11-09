"""Process-wide defaults: shared ``Client`` / ``AsyncClient`` and active project."""

from __future__ import annotations

import asyncio
import logging
import re
import sys
import types
import weakref

from opengrade import _config, _state
from opengrade._http import OpengradeAPIError, OpengradeError
from opengrade.async_client import AsyncClient
from opengrade.client import Client
from opengrade.models import ProjectResponse

__all__ = ["AsyncClient", "Client"]

logger = logging.getLogger("opengrade")

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(value: str) -> str:
    # Mirrors the server's slugify so lookups match what create() would store.
    slug = _SLUG_RE.sub("-", value.strip().lower()).strip("-")
    return slug or "project"


def get_client() -> Client:
    """Return the ``Client`` for ``opengrade.current()``."""
    from opengrade._opengrade import current

    return current().client


def get_async_client() -> AsyncClient:
    """Return the ``AsyncClient`` for ``opengrade.current()`` and the running loop."""
    from opengrade._opengrade import current

    return current().async_client()


def _aclose_async_client_best_effort(client: AsyncClient) -> None:
    """Close an async client from sync code; never raise into the host app."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        try:
            asyncio.run(client.aclose())
        except Exception:  # noqa: BLE001
            logger.debug("opengrade: async client close raised", exc_info=True)
        return
    logger.warning(
        "opengrade: dropping shared AsyncClient without aclose() "
        "(event loop is running; await get_async_client().aclose() before set_tracking_uri)"
    )


def _close_runtime_clients(rt: _state._Runtime) -> None:
    with rt.client_lock:
        if rt.client is not None:
            rt.client.close()
        rt.client = None
        async_clients = list(rt.async_clients.values())
        rt.async_clients.clear()
        no_loop = rt.async_client_no_loop
        rt.async_client_no_loop = None
    for async_client in async_clients:
        _aclose_async_client_best_effort(async_client)
    if no_loop is not None:
        _aclose_async_client_best_effort(no_loop)


def _reset_client() -> None:
    _close_runtime_clients(_state._default())


def _find_project(client: Client, name: str, slug: str) -> ProjectResponse | None:
    by_slug = client.projects.list(slug=slug)
    if by_slug:
        return by_slug[0]
    by_name = client.projects.list(name=name)
    return by_name[0] if by_name else None


async def _afind_project(client: AsyncClient, name: str, slug: str) -> ProjectResponse | None:
    by_slug = await client.projects.list(slug=slug)
    if by_slug:
        return by_slug[0]
    by_name = await client.projects.list(name=name)
    return by_name[0] if by_name else None


def _activate_project(
    project: ProjectResponse,
    cleaned: str,
    rt: _state._Runtime | None = None,
) -> ProjectResponse:
    from opengrade import _otel

    if rt is None:
        from opengrade._opengrade import current

        rt = current()._runtime
    active_id = _state._active_project_id() if rt is _state._default() else rt.settings.project_id
    if _otel._INITIALIZED and active_id != project.id:
        logger.warning(
            "opengrade.set_project(%r) after init(): traces keep going to the previous "
            "project until opengrade.init(force=True)",
            cleaned,
        )
    rt.active_project = project
    if rt is _state._default():
        _config._set_active_project(project_id=project.id, project_slug=project.slug)
    else:
        rt.settings = rt.settings.with_updates(project_id=project.id, project_slug=project.slug)
    # Keep mock transports / open connections; only refresh the bound project.
    if rt.client is not None:
        rt.client._project_id = project.id
    if rt.async_client_no_loop is not None:
        rt.async_client_no_loop._project_id = project.id
    for async_client in list(rt.async_clients.values()):
        async_client._project_id = project.id
    return project


def resolve_or_create_project(
    name: str,
    client: Client,
    *,
    activate: bool = True,
    runtime: _state._Runtime | None = None,
) -> ProjectResponse | None:
    """Find or create ``name`` on ``client``. Optionally make it the active project.

    On platform unreachable / API failure, logs a warning and returns ``None``.
    """
    cleaned = name.strip()
    if not cleaned:
        raise ValueError("project name must not be empty")
    slug = _slugify(cleaned)

    try:
        project = _find_project(client, cleaned, slug)
        if project is None:
            try:
                project = client.projects.create(name=cleaned, slug=slug)
                logger.info("opengrade created project %r (slug=%s)", cleaned, slug)
            except OpengradeAPIError as exc:
                if exc.status != 409:
                    raise
                # Created concurrently by another process — use theirs.
                project = _find_project(client, cleaned, slug)
                if project is None:
                    raise
    except OpengradeError as exc:
        logger.warning("opengrade.set_project(%r) failed: %s", cleaned, exc)
        return None

    if activate:
        if runtime is None:
            from opengrade._opengrade import current

            runtime = current()._runtime
        return _activate_project(project, cleaned, runtime)
    return project


def set_project(name: str) -> ProjectResponse | None:
    """Make ``name`` the active project, creating it if missing.

    Matches an existing project by slug (``slugify(name)``) or exact name.
    ``opengrade.init()`` called afterwards exports traces to this project.

    On platform unreachable / API failure, logs a warning and returns ``None``
    so app startup is never blocked by a down opengrade host.
    """
    return resolve_or_create_project(name, get_client(), activate=True)


async def aset_project(name: str) -> ProjectResponse | None:
    """Async variant of ``set_project`` using the shared ``AsyncClient``."""
    cleaned = name.strip()
    if not cleaned:
        raise ValueError("project name must not be empty")
    slug = _slugify(cleaned)
    client = get_async_client()

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

    from opengrade._opengrade import current

    return _activate_project(project, cleaned, current()._runtime)


def get_project() -> ProjectResponse | None:
    """Return the project set via ``set_project`` on ``current()``, if any."""
    from opengrade._opengrade import current

    return current()._runtime.active_project


def _reset_for_tests() -> None:
    from opengrade._opengrade import _reset_opengrade_for_tests

    _reset_client()
    _state._reset_default_for_tests()
    _reset_opengrade_for_tests()
    _config._reset_for_tests()


def _after_fork_in_child() -> None:
    """Test helper only: resets client refs. Real forks use
    ``_state._after_fork_in_child`` (registered once), which also clears pool/sender."""
    _state._default().reset_client_refs()


class _ContextModule(types.ModuleType):
    """Pytest contract: attribute assignment like ``_context._CLIENT = …`` must
    mutate the default ``_Runtime``, not a vanished module global."""

    @property
    def _CLIENT(self) -> Client | None:
        return _state._default().client

    @_CLIENT.setter
    def _CLIENT(self, value: Client | None) -> None:
        _state._default().client = value

    @property
    def _ASYNC_CLIENT_NO_LOOP(self) -> AsyncClient | None:
        return _state._default().async_client_no_loop

    @_ASYNC_CLIENT_NO_LOOP.setter
    def _ASYNC_CLIENT_NO_LOOP(self, value: AsyncClient | None) -> None:
        _state._default().async_client_no_loop = value

    @property
    def _ASYNC_CLIENTS(self) -> weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, AsyncClient]:
        return _state._default().async_clients


sys.modules[__name__].__class__ = _ContextModule
