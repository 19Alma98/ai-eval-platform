"""Bound project id resolution for Client / AsyncClient."""

from __future__ import annotations

from collections.abc import Callable

ProjectResolver = Callable[[str | None], str]


def resolve_bound_project(
    project_id: str | None,
    *,
    bound: str | None,
) -> str:
    """Explicit method arg, else client-bound id. No process-wide fallback."""
    if project_id:
        return project_id
    if bound:
        return bound
    raise ValueError(
        "project_id is required: pass Client(..., project_id=...) or the method argument"
    )
