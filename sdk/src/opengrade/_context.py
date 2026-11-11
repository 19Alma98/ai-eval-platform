"""Client helpers and project activation for an ``Opengrade`` runtime."""

from __future__ import annotations

import asyncio
import logging
import re

from opengrade import _state
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
        "(event loop is running; await async_client().aclose() before replacing settings)"
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
    rt: _state._Runtime,
) -> ProjectResponse:

    active_id = rt.settings.project_id
    if rt.initialized and active_id != project.id:
        logger.warning(
            "Opengrade.set_project(%r) after init_tracing(): traces keep going to the previous "
            "project until init_tracing(force=True)",
            cleaned,
        )
    rt.active_project = project
    _state.set_active_project(rt, project_id=project.id, project_slug=project.slug)
    # Keep mock transports / open connections; only refresh the bound project.
    if rt.client is not None:
        rt.client._project_id = project.id
    if rt.async_client_no_loop is not None:
        rt.async_client_no_loop._project_id = project.id
    for async_client in list(rt.async_clients.values()):
        async_client._project_id = project.id
    return project


def ensure_project(rt: _state._Runtime, client: Client | None = None) -> str | None:
    """Find or create the project named by ``Settings.project``; its id, or None.

    Used where no one called ``set_project``: before the first span export (on the
    exporter's thread, never on the traced call) and on the first control-plane call.
    Quiet on failure (the caller reports it) and retried on the next call.
    """
    with rt.ensure_project_lock:
        if rt.settings.project_id:
            return rt.settings.project_id
        name = (rt.settings.project or "").strip()
        if not name:
            return None
        slug = rt.settings.project_slug or _slugify(name)
        if client is None:
            from opengrade._opengrade import client_for_runtime

            client = client_for_runtime(rt)
        try:
            project = _find_project(client, name, slug)
            if project is None:
                try:
                    project = client.projects.create(name=name, slug=slug)
                    logger.info("opengrade created project %r (slug=%s)", name, slug)
                except OpengradeAPIError as exc:
                    if exc.status != 409:
                        raise
                    project = _find_project(client, name, slug)  # created concurrently
                    if project is None:
                        raise
        except OpengradeError as exc:
            logger.debug("opengrade: could not find or create project %r: %s", name, exc)
            return None
        rt.active_project = project
        _state.set_active_project(rt, project_id=project.id, project_slug=project.slug)
        for bound in (rt.client, rt.async_client_no_loop, *list(rt.async_clients.values())):
            if bound is not None:
                bound._project_id = project.id
        return project.id


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
        logger.warning("Opengrade.set_project(%r) failed: %s", cleaned, exc)
        return None

    if activate:
        if runtime is None:
            from opengrade._opengrade import current

            runtime = current()._runtime
        return _activate_project(project, cleaned, runtime)
    return project
