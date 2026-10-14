"""Process-wide defaults: shared ``Client`` and active project (``set_project``)."""

from __future__ import annotations

import logging
import os
import re
import threading

from aiobs import _config
from aiobs._http import AiobsAPIError
from aiobs.client import Client
from aiobs.models import ProjectResponse

logger = logging.getLogger("aiobs")

_SLUG_RE = re.compile(r"[^a-z0-9]+")

_LOCK = threading.Lock()
_CLIENT: Client | None = None
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


def _reset_client() -> None:
    global _CLIENT
    with _LOCK:
        if _CLIENT is not None:
            _CLIENT.close()
        _CLIENT = None


def _find_project(client: Client, name: str, slug: str) -> ProjectResponse | None:
    projects = client.projects.list()
    for project in projects:
        if project.slug == slug:
            return project
    for project in projects:
        if project.name == name:
            return project
    return None


def set_project(name: str) -> ProjectResponse:
    """Make ``name`` the active project, creating it if missing.

    Matches an existing project by slug (``slugify(name)``) or exact name.
    ``aiobs.init()`` called afterwards exports traces to this project.
    """
    global _ACTIVE_PROJECT
    cleaned = name.strip()
    if not cleaned:
        raise ValueError("project name must not be empty")
    slug = _slugify(cleaned)
    client = get_client()

    project = _find_project(client, cleaned, slug)
    if project is None:
        try:
            project = client.projects.create(name=cleaned, slug=slug)
            logger.info("aiobs created project %r (slug=%s)", cleaned, slug)
        except AiobsAPIError as exc:
            if exc.status != 409:
                raise
            # Created concurrently by another process — use theirs.
            project = _find_project(client, cleaned, slug)
            if project is None:
                raise

    from aiobs import _otel

    if _otel._INITIALIZED and _config._ACTIVE_PROJECT_ID != project.id:
        logger.warning(
            "aiobs.set_project(%r) after init(): traces keep going to the previous "
            "project until aiobs.init(force=True)",
            cleaned,
        )
    _ACTIVE_PROJECT = project
    _config._set_active_project(project_id=project.id, project_slug=project.slug)
    return project


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
    global _CLIENT, _LOCK
    _CLIENT = None
    _LOCK = threading.Lock()


if hasattr(os, "register_at_fork"):  # not on Windows
    os.register_at_fork(after_in_child=_after_fork_in_child)
