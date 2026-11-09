from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from urllib.parse import urlsplit

DEFAULT_TRACKING_URI = "http://localhost:8000"
OTLP_TRACES_PATH = "/v1/traces"
DEFAULT_ENDPOINT = DEFAULT_TRACKING_URI + OTLP_TRACES_PATH
DEFAULT_SERVICE_NAME = "opengrade-app"
DEFAULT_MAX_CAPTURE_BYTES = 32 * 1024
# Back-compat alias for the default capture limit (prefer ``max_capture_bytes()``).
MAX_CAPTURE_BYTES = DEFAULT_MAX_CAPTURE_BYTES

logger = logging.getLogger("opengrade")

_TRACKING_URI: str | None = None
_API_KEY: str | None = None
_WARNED_PLAINTEXT_KEY = False
_ACTIVE_PROJECT_ID: str | None = None
_ACTIVE_PROJECT_SLUG: str | None = None
_MAX_CAPTURE_BYTES: int | None = None


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
        from opengrade._context import _reset_client

        _reset_client()


def get_tracking_uri() -> str:
    """Resolve the platform URI.

    Order: ``set_tracking_uri()`` > ``OPENGRADE_TRACKING_URI`` > ``http://localhost:8000``.
    """
    if _TRACKING_URI is not None:
        return _TRACKING_URI
    value = os.getenv("OPENGRADE_TRACKING_URI")
    if value and value.strip():
        return _normalize_uri(value)
    return DEFAULT_TRACKING_URI


def set_api_key(key: str | None) -> None:
    """Set the platform API key used by ``Client()`` and OTLP export (``None`` clears it)."""
    normalized = key.strip() if key is not None else None
    global _API_KEY
    if normalized != _API_KEY:
        _API_KEY = normalized or None
        from opengrade._context import _reset_client

        _reset_client()


def get_api_key() -> str | None:
    """Resolve the platform API key: ``set_api_key()`` > ``OPENGRADE_API_KEY`` > none."""
    if _API_KEY is not None:
        return _API_KEY
    value = (os.getenv("OPENGRADE_API_KEY") or "").strip()
    return value or None


def _is_loopback_host(host: str) -> bool:
    return host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".localhost")


def auth_headers(url: str, api_key: str | None = None) -> dict[str, str]:
    """``Authorization: Bearer`` header for ``url`` when a key is configured.

    Warns once when the key would travel over plain HTTP to a non-loopback host.
    """
    key = api_key if api_key is not None else get_api_key()
    if not key:
        return {}
    parsed = urlsplit(url)
    global _WARNED_PLAINTEXT_KEY
    if (
        parsed.scheme == "http"
        and not _is_loopback_host(parsed.hostname or "")
        and not _WARNED_PLAINTEXT_KEY
    ):
        _WARNED_PLAINTEXT_KEY = True
        logger.warning(
            "opengrade: sending the API key over plain HTTP to %s; use https:// so it "
            "cannot be read on the network",
            parsed.hostname,
        )
    return {"Authorization": f"Bearer {key}"}


def otlp_endpoint() -> str:
    """OTLP traces URL: ``OPENGRADE_OTLP_ENDPOINT`` override, else ``<tracking_uri>/v1/traces``."""
    override = os.getenv("OPENGRADE_OTLP_ENDPOINT")
    if override and override.strip():
        return override.strip()
    return get_tracking_uri() + OTLP_TRACES_PATH


def _lazy_resolve_slug(slug: str) -> str | None:
    """Resolve a project slug to an id via the control plane; cache on success."""
    global _ACTIVE_PROJECT_ID, _ACTIVE_PROJECT_SLUG
    try:
        from opengrade._context import get_client

        projects = get_client().projects.list(slug=slug)
        if projects:
            project = projects[0]
            _ACTIVE_PROJECT_ID = project.id
            _ACTIVE_PROJECT_SLUG = project.slug
            return project.id
    except Exception as exc:  # noqa: BLE001 — never raise into log_score / metrics
        logger.warning("opengrade: could not resolve project slug %r: %s", slug, exc)
        return None
    logger.warning("opengrade: project slug %r not found", slug)
    return None


def resolve_project_id(project_id: str | None = None) -> str:
    """Project id for control-plane calls.

    Precedence: argument > ``init``/``set_project`` id > ``OPENGRADE_PROJECT_ID`` >
    lazy slug resolve (``init``/``set_project`` slug / ``OPENGRADE_PROJECT_SLUG``).
    """
    if project_id:
        return project_id
    if _ACTIVE_PROJECT_ID:
        return _ACTIVE_PROJECT_ID
    env_id = os.getenv("OPENGRADE_PROJECT_ID")
    if env_id and env_id.strip():
        return env_id.strip()
    slug = _ACTIVE_PROJECT_SLUG or (os.getenv("OPENGRADE_PROJECT_SLUG") or "").strip() or None
    if slug:
        resolved = _lazy_resolve_slug(slug)
        if resolved:
            return resolved
    raise ValueError(
        "No project: pass project_id, call opengrade.set_project() / init(project_…), "
        "or set OPENGRADE_PROJECT_ID / OPENGRADE_PROJECT_SLUG"
    )


def _set_active_project(
    *,
    project_id: str | None = None,
    project_slug: str | None = None,
) -> None:
    global _ACTIVE_PROJECT_ID, _ACTIVE_PROJECT_SLUG
    if project_id is not None:
        _ACTIVE_PROJECT_ID = project_id
    if project_slug is not None:
        _ACTIVE_PROJECT_SLUG = project_slug


def configure_capture(*, max_capture_bytes: int | None = None) -> None:
    """Set capture limit from ``init()``; ``None`` falls back to the env var / default."""
    global _MAX_CAPTURE_BYTES
    if max_capture_bytes is None:
        _MAX_CAPTURE_BYTES = None
        return
    value = int(max_capture_bytes)
    if value < 1:
        raise ValueError(f"max_capture_bytes must be >= 1, got {value}")
    _MAX_CAPTURE_BYTES = value


def max_capture_bytes() -> int:
    """``init(max_capture_bytes=...)`` > ``OPENGRADE_MAX_CAPTURE_BYTES`` > 32768."""
    if _MAX_CAPTURE_BYTES is not None:
        return _MAX_CAPTURE_BYTES
    raw = os.getenv("OPENGRADE_MAX_CAPTURE_BYTES", "").strip()
    if not raw:
        return DEFAULT_MAX_CAPTURE_BYTES
    try:
        value = int(raw)
        if value < 1:
            raise ValueError
        return value
    except ValueError:
        logger.warning(
            "opengrade: invalid OPENGRADE_MAX_CAPTURE_BYTES=%r; using %d",
            raw,
            DEFAULT_MAX_CAPTURE_BYTES,
        )
        return DEFAULT_MAX_CAPTURE_BYTES


def _reset_for_tests() -> None:
    global _TRACKING_URI, _ACTIVE_PROJECT_ID, _ACTIVE_PROJECT_SLUG, _API_KEY, _WARNED_PLAINTEXT_KEY
    global _MAX_CAPTURE_BYTES
    _TRACKING_URI = None
    _API_KEY = None
    _WARNED_PLAINTEXT_KEY = False
    _ACTIVE_PROJECT_ID = None
    _ACTIVE_PROJECT_SLUG = None
    _MAX_CAPTURE_BYTES = None


@dataclass(frozen=True, slots=True)
class ResolvedConfig:
    endpoint: str
    service_name: str
    project_id: str | None
    project_slug: str | None
    version: str | None = None
    environment: str | None = None


def resolve_config(
    *,
    project_id: str | None = None,
    project_slug: str | None = None,
    endpoint: str | None = None,
    service_name: str | None = None,
    version: str | None = None,
    environment: str | None = None,
) -> ResolvedConfig:
    explicit_both = project_id is not None and project_slug is not None
    if explicit_both:
        raise ValueError(
            "Provide exactly one of project_id / project_slug "
            "(arguments, opengrade.set_project(), or OPENGRADE_PROJECT_ID / OPENGRADE_PROJECT_SLUG)"
        )

    pid = project_id
    pslug = project_slug
    if pid is None and pslug is None:
        if _ACTIVE_PROJECT_ID is not None:
            # set_project() / init(project_id=…) wins over env.
            pid = _ACTIVE_PROJECT_ID
        elif _ACTIVE_PROJECT_SLUG is not None:
            pslug = _ACTIVE_PROJECT_SLUG
        else:
            pid = os.getenv("OPENGRADE_PROJECT_ID")
            pslug = os.getenv("OPENGRADE_PROJECT_SLUG")
    # Treat empty strings as unset
    pid = pid or None
    pslug = pslug or None

    # Dual env (or active id+slug): id wins over slug for OTLP headers.
    if pid is not None and pslug is not None:
        pslug = None

    if pid is None and pslug is None:
        raise ValueError(
            "Provide project_id or project_slug "
            "(arguments, opengrade.set_project() / init(), or "
            "OPENGRADE_PROJECT_ID / OPENGRADE_PROJECT_SLUG)"
        )

    return ResolvedConfig(
        endpoint=endpoint or otlp_endpoint(),
        service_name=service_name or os.getenv("OPENGRADE_SERVICE_NAME") or DEFAULT_SERVICE_NAME,
        project_id=pid,
        project_slug=pslug,
        version=version or os.getenv("OPENGRADE_VERSION") or None,
        environment=environment or os.getenv("OPENGRADE_ENVIRONMENT") or None,
    )


def project_headers(config: ResolvedConfig) -> dict[str, str]:
    if config.project_id:
        return {"X-Project-Id": config.project_id}
    assert config.project_slug is not None
    return {"X-Project-Slug": config.project_slug}
