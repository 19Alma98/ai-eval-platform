"""Bound project id resolution for Client / AsyncClient (global fallback is deprecated)."""

from __future__ import annotations

import warnings
from collections.abc import Callable

from opengrade._config import resolve_project_id

ProjectResolver = Callable[[str | None], str]

_GLOBAL_FALLBACK_WARNED = False

_DEPRECATION_MSG = (
    "Resolving project_id from process-wide opengrade state without an explicit "
    "Client(..., project_id=...) or method argument is deprecated; pass project_id "
    "on the client or each call."
)


def resolve_bound_project(
    project_id: str | None,
    *,
    bound: str | None,
    stacklevel: int = 2,
) -> str:
    """Explicit arg > client-bound id > global ``resolve_project_id`` (warn once)."""
    global _GLOBAL_FALLBACK_WARNED
    if project_id:
        return project_id
    if bound:
        return bound
    if not _GLOBAL_FALLBACK_WARNED:
        warnings.warn(_DEPRECATION_MSG, DeprecationWarning, stacklevel=stacklevel + 1)
        _GLOBAL_FALLBACK_WARNED = True
    return resolve_project_id(None)


def reset_global_fallback_warning_for_tests() -> None:
    """Allow tests to observe the deprecation warning more than once."""
    global _GLOBAL_FALLBACK_WARNED
    _GLOBAL_FALLBACK_WARNED = False
