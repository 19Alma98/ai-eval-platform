"""Stable UI links for SDK objects.

Paths match the UI routes (frontend ``lib/links.ts``): every experiment, experiment
item and trace has one URL that keeps working, with ``?project=`` selecting the project.
"""

from __future__ import annotations

import os
from urllib.parse import quote, urlencode


def ui_base_url(api_base_url: str) -> str:
    """UI host for result links: ``AIOBS_UI_URL``, else the API host (it serves the UI)."""
    override = os.getenv("AIOBS_UI_URL")
    if override and override.strip():
        return override.strip().rstrip("/")
    return api_base_url.rstrip("/")


def _url(base: str, path: str, project_id: str | None, **query: str) -> str:
    params = {**query, **({"project": project_id} if project_id else {})}
    qs = urlencode(params)
    return f"{base.rstrip('/')}{path}" + (f"?{qs}" if qs else "")


def experiment_url(base: str, experiment_id: str, project_id: str | None) -> str:
    return _url(base, f"/experiments/{quote(experiment_id, safe='')}", project_id)


def experiment_item_url(
    base: str, experiment_id: str, dataset_item_id: str, project_id: str | None
) -> str:
    return _url(
        base, f"/experiments/{quote(experiment_id, safe='')}", project_id, item=dataset_item_id
    )


def trace_url(base: str, trace_id: str, project_id: str | None) -> str:
    return _url(base, f"/traces/{quote(trace_id, safe='')}", project_id)
