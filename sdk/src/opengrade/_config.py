from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_TRACKING_URI = "http://localhost:8000"
OTLP_TRACES_PATH = "/v1/traces"
DEFAULT_ENDPOINT = DEFAULT_TRACKING_URI + OTLP_TRACES_PATH
DEFAULT_SERVICE_NAME = "aiobs-app"
MAX_CAPTURE_BYTES = 32 * 1024

_TRACKING_URI: str | None = None
_ACTIVE_PROJECT_ID: str | None = None
_ACTIVE_PROJECT_SLUG: str | None = None


def _normalize_uri(uri: str) -> str:
    return uri.strip().rstrip("/")


def set_tracking_uri(uri: str) -> None:
    """Set the platform URI used by both ``Client()`` and OTLP export."""
    normalized = _normalize_uri(uri)
    if not normalized:
        raise ValueError("tracking URI must not be empty")
    global _TRACKING_URI
    if normalized != _TRACKING_URI:
        _TRACKING_URI = normalized
        from aiobs._context import _reset_client

        _reset_client()


def get_tracking_uri() -> str:
    """Resolve the platform URI.

    Order: ``set_tracking_uri()`` > ``AIOBS_TRACKING_URI`` > ``http://localhost:8000``.
    """
    if _TRACKING_URI is not None:
        return _TRACKING_URI
    value = os.getenv("AIOBS_TRACKING_URI")
    if value and value.strip():
        return _normalize_uri(value)
    return DEFAULT_TRACKING_URI


def otlp_endpoint() -> str:
    """OTLP traces URL: ``AIOBS_OTLP_ENDPOINT`` override, else ``<tracking_uri>/v1/traces``."""
    override = os.getenv("AIOBS_OTLP_ENDPOINT")
    if override and override.strip():
        return override.strip()
    return get_tracking_uri() + OTLP_TRACES_PATH


def resolve_project_id(project_id: str | None = None) -> str:
    """Project id for control-plane calls: argument > ``set_project()`` > ``AIOBS_PROJECT_ID``."""
    resolved = project_id or _ACTIVE_PROJECT_ID or os.getenv("AIOBS_PROJECT_ID")
    if not resolved:
        raise ValueError(
            "No project: pass project_id, call aiobs.set_project(), or set AIOBS_PROJECT_ID"
        )
    return resolved


def _set_active_project(*, project_id: str, project_slug: str) -> None:
    global _ACTIVE_PROJECT_ID, _ACTIVE_PROJECT_SLUG
    _ACTIVE_PROJECT_ID = project_id
    _ACTIVE_PROJECT_SLUG = project_slug


def _reset_for_tests() -> None:
    global _TRACKING_URI, _ACTIVE_PROJECT_ID, _ACTIVE_PROJECT_SLUG
    _TRACKING_URI = None
    _ACTIVE_PROJECT_ID = None
    _ACTIVE_PROJECT_SLUG = None


@dataclass(frozen=True, slots=True)
class ResolvedConfig:
    endpoint: str
    service_name: str
    project_id: str | None
    project_slug: str | None


def resolve_config(
    *,
    project_id: str | None = None,
    project_slug: str | None = None,
    endpoint: str | None = None,
    service_name: str | None = None,
) -> ResolvedConfig:
    pid = project_id
    pslug = project_slug
    if pid is None and pslug is None:
        if _ACTIVE_PROJECT_ID is not None:
            # set_project() wins over env: it is the explicit in-process choice.
            pid = _ACTIVE_PROJECT_ID
        else:
            pid = os.getenv("AIOBS_PROJECT_ID")
            pslug = os.getenv("AIOBS_PROJECT_SLUG")
    # Treat empty strings as unset
    pid = pid or None
    pslug = pslug or None

    if (pid is None) == (pslug is None):
        raise ValueError(
            "Provide exactly one of project_id / project_slug "
            "(arguments, aiobs.set_project(), or AIOBS_PROJECT_ID / AIOBS_PROJECT_SLUG)"
        )

    return ResolvedConfig(
        endpoint=endpoint or otlp_endpoint(),
        service_name=service_name or os.getenv("AIOBS_SERVICE_NAME") or DEFAULT_SERVICE_NAME,
        project_id=pid,
        project_slug=pslug,
    )


def project_headers(config: ResolvedConfig) -> dict[str, str]:
    if config.project_id:
        return {"X-Project-Id": config.project_id}
    assert config.project_slug is not None
    return {"X-Project-Slug": config.project_slug}
