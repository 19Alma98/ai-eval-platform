"""Process-wide defaults: shared ``Client`` / ``AsyncClient`` and active project."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import threading
import weakref

from opengrade import _config
from opengrade._http import OpengradeAPIError, OpengradeError
from opengrade.async_client import AsyncClient
from opengrade.client import Client
from opengrade.models import ProjectResponse

logger = logging.getLogger("opengrade")

_SLUG_RE = re.compile(r"[^a-z0-9]+")

_LOCK = threading.Lock()
_CLIENT: Client | None = None
# One AsyncClient per running event loop (second asyncio.run must not reuse a closed loop).
_ASYNC_CLIENTS: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, AsyncClient] = (
    weakref.WeakKeyDictionary()
)
# Fallback when get_async_client() is called with no running loop (sync bridge / tests).
_ASYNC_CLIENT_NO_LOOP: AsyncClient | None = None
_ACTIVE_PROJECT: ProjectResponse | None = None


def _slugify(value: str) -> str:
    # Mirrors the server's slugify so lookups match what create() would store.
    slug = _SLUG_RE.sub("-", value.strip().lower()).strip("-")
    return slug or "project"


def get_client() -> Client:
    """Return the shared ``Client`` bound to the current tracking URI."""
    global _CLIENT
    with _LOCK:
        if _CLIENT is None:
            _CLIENT = Client(_config.get_tracking_uri())
        return _CLIENT


def get_async_client() -> AsyncClient:
    """Return an ``AsyncClient`` bound to the current tracking URI and event loop."""
    global _ASYNC_CLIENT_NO_LOOP
    uri = _config.get_tracking_uri()
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        with _LOCK:
            if _ASYNC_CLIENT_NO_LOOP is None:
                _ASYNC_CLIENT_NO_LOOP = AsyncClient(uri)
            return _ASYNC_CLIENT_NO_LOOP
    with _LOCK:
        client = _ASYNC_CLIENTS.get(loop)
        if client is None:
            client = AsyncClient(uri)
            _ASYNC_CLIENTS[loop] = client
        return client


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


def _reset_client() -> None:
    global _CLIENT, _ASYNC_CLIENT_NO_LOOP
    with _LOCK:
        if _CLIENT is not None:
            _CLIENT.close()
        _CLIENT = None
        async_clients = list(_ASYNC_CLIENTS.values())
        _ASYNC_CLIENTS.clear()
        no_loop = _ASYNC_CLIENT_NO_LOOP
        _ASYNC_CLIENT_NO_LOOP = None
    for async_client in async_clients:
        _aclose_async_client_best_effort(async_client)
    if no_loop is not None:
        _aclose_async_client_best_effort(no_loop)


def _find_project(client: Client, name: str, slug: str) -> ProjectResponse | None:
    projects = client.projects.list()
    for project in projects:
        if project.slug == slug:
            return project
    for project in projects:
        if project.name == name:
            return project
    return None


async def _afind_project(client: AsyncClient, name: str, slug: str) -> ProjectResponse | None:
    projects = await client.projects.list()
    for project in projects:
        if project.slug == slug:
            return project
    for project in projects:
        if project.name == name:
            return project
    return None


def _activate_project(project: ProjectResponse, cleaned: str) -> ProjectResponse:
    global _ACTIVE_PROJECT
    from opengrade import _otel

    if _otel._INITIALIZED and _config._ACTIVE_PROJECT_ID != project.id:
        logger.warning(
            "opengrade.set_project(%r) after init(): traces keep going to the previous "
            "project until opengrade.init(force=True)",
            cleaned,
        )
    _ACTIVE_PROJECT = project
    _config._set_active_project(project_id=project.id, project_slug=project.slug)
    return project


def resolve_or_create_project(
    name: str,
    client: Client,
    *,
    activate: bool = True,
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
        return _activate_project(project, cleaned)
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

    return _activate_project(project, cleaned)


def get_project() -> ProjectResponse | None:
    """Return the project set via ``set_project``, if any."""
    return _ACTIVE_PROJECT


def _reset_for_tests() -> None:
    global _ACTIVE_PROJECT
    _reset_client()
    _ACTIVE_PROJECT = None
    _config._reset_for_tests()


def _after_fork_in_child() -> None:
    """The child inherits the parent's httpx client (sockets/locks); drop it so
    the child lazily builds a fresh one. Do not close — that would affect the parent."""
    global _CLIENT, _ASYNC_CLIENT_NO_LOOP, _ASYNC_CLIENTS, _LOCK
    _CLIENT = None
    _ASYNC_CLIENT_NO_LOOP = None
    _ASYNC_CLIENTS = weakref.WeakKeyDictionary()
    _LOCK = threading.Lock()


if hasattr(os, "register_at_fork"):  # not on Windows
    os.register_at_fork(after_in_child=_after_fork_in_child)
