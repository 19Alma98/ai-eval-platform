from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from opengrade import _state
from opengrade._state import Settings, _Runtime

DEFAULT_TRACKING_URI = "http://localhost:8000"
OTLP_TRACES_PATH = "/v1/traces"
DEFAULT_ENDPOINT = DEFAULT_TRACKING_URI + OTLP_TRACES_PATH
DEFAULT_SERVICE_NAME = "opengrade-app"
DEFAULT_MAX_CAPTURE_BYTES = 32 * 1024

logger = logging.getLogger("opengrade")

_UNSET: Any = object()

RedactFn = Callable[[str, Any], Any]
RedactOutputFn = Callable[[Any], Any]


def _normalize_uri(uri: str) -> str:
    return uri.strip().rstrip("/")


def _is_loopback_host(host: str) -> bool:
    return host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".localhost")


def auth_headers(
    url: str, api_key: str | None = None, *, runtime: _Runtime | None = None
) -> dict[str, str]:
    """``Authorization: Bearer`` header for ``url`` when a key is configured.

    Warns once when the key would travel over plain HTTP to a non-loopback host.
    """
    key = api_key
    rt = runtime
    if key is None and rt is not None:
        key = _state.api_key_for(rt)
    if key is None:
        key = (os.getenv("OPENGRADE_API_KEY") or "").strip() or None
    if not key:
        return {}
    parsed = urlsplit(url)
    warn_rt = rt
    if (
        parsed.scheme == "http"
        and not _is_loopback_host(parsed.hostname or "")
        and warn_rt is not None
        and not warn_rt.settings.warned_plaintext_key
    ):
        warn_rt.settings = warn_rt.settings.with_updates(warned_plaintext_key=True)
        logger.warning(
            "opengrade: sending the API key over plain HTTP to %s; use https:// so it "
            "cannot be read on the network",
            parsed.hostname,
        )
    return {"Authorization": f"Bearer {key}"}


def otlp_endpoint(*, tracking_uri: str | None = None, runtime: _Runtime | None = None) -> str:
    """OTLP traces URL: ``OPENGRADE_OTLP_ENDPOINT`` override, else ``<tracking_uri>/v1/traces``."""
    override = os.getenv("OPENGRADE_OTLP_ENDPOINT")
    if override and override.strip():
        return override.strip()
    if tracking_uri is not None:
        base = _normalize_uri(tracking_uri)
    elif runtime is not None:
        base = _state.tracking_uri_for(runtime)
    else:
        base = DEFAULT_TRACKING_URI
    return base + OTLP_TRACES_PATH


def _lazy_resolve_slug(rt: _Runtime, slug: str, *, client: Any | None = None) -> str | None:
    """Resolve a project slug to an id via by-slug lookup; cache success and 404."""
    if _state.is_slug_not_found(rt, slug):
        return None
    try:
        from opengrade._errors import OpengradeAPIError

        if client is None:
            from opengrade._opengrade import current

            client = current().client
        project = client.projects.get_by_slug(slug)
        _state.set_active_project(rt, project_id=project.id, project_slug=project.slug)
        return project.id
    except OpengradeAPIError as exc:
        if exc.status == 404:
            _state.mark_slug_not_found(rt, slug)
            logger.warning("opengrade: project slug %r not found", slug)
            return None
        logger.warning("opengrade: could not resolve project slug %r: %s", slug, exc)
        return None
    except Exception as exc:  # noqa: BLE001 — never raise into log_score / metrics
        logger.warning("opengrade: could not resolve project slug %r: %s", slug, exc)
        return None


def resolve_project_id(
    project_id: str | None = None,
    *,
    runtime: _Runtime | None = None,
    client: Any | None = None,
) -> str:
    """Project id for control-plane calls on ``runtime`` (default: active)."""
    if project_id:
        return project_id
    rt = runtime if runtime is not None else _state.active_runtime()
    if rt.settings.project_id:
        return rt.settings.project_id
    slug = rt.settings.project_slug
    if slug:
        resolved = _lazy_resolve_slug(rt, slug, client=client)
        if resolved:
            return resolved
    raise ValueError(
        "No project: pass project_id, call Opengrade.set_project() / Settings(project_…), "
        "or set OPENGRADE_PROJECT_ID / OPENGRADE_PROJECT_SLUG when constructing Settings"
    )


def configure_capture(
    rt: _Runtime,
    *,
    max_capture_bytes: int | None | Any = _UNSET,
    redact: RedactFn | None | Any = _UNSET,
    redact_output: RedactOutputFn | None | Any = _UNSET,
) -> None:
    """Configure capture limit and optional redactors on ``rt``."""
    if max_capture_bytes is _UNSET and redact is _UNSET and redact_output is _UNSET:
        rt.settings = rt.settings.with_updates(max_capture_bytes=None)
        rt.capture_redact = None
        rt.capture_redact_output = None
        return
    if max_capture_bytes is not _UNSET:
        if max_capture_bytes is None:
            rt.settings = rt.settings.with_updates(max_capture_bytes=None)
        else:
            value = int(max_capture_bytes)
            if value < 1:
                raise ValueError(f"max_capture_bytes must be >= 1, got {value}")
            rt.settings = rt.settings.with_updates(max_capture_bytes=value)
    if redact is not _UNSET:
        rt.capture_redact = redact
    if redact_output is not _UNSET:
        rt.capture_redact_output = redact_output


def capture_redact(runtime: _Runtime | None = None) -> RedactFn | None:
    rt = runtime if runtime is not None else _state.active_runtime_or_none()
    return None if rt is None else rt.capture_redact


def capture_redact_output(runtime: _Runtime | None = None) -> RedactOutputFn | None:
    rt = runtime if runtime is not None else _state.active_runtime_or_none()
    return None if rt is None else rt.capture_redact_output


def max_capture_bytes(runtime: _Runtime | None = None) -> int:
    """Settings override > 32768 (env already applied in ``Settings.from_env``)."""
    rt = runtime if runtime is not None else _state.active_runtime_or_none()
    if rt is None:
        return DEFAULT_MAX_CAPTURE_BYTES
    override = rt.settings.max_capture_bytes
    if override is not None:
        if override < 1:
            return DEFAULT_MAX_CAPTURE_BYTES
        return override
    return DEFAULT_MAX_CAPTURE_BYTES


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
    runtime: _Runtime | None = None,
    settings: Settings | None = None,
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
            "(arguments or Settings.project_id / Settings.project_slug)"
        )

    rt = runtime
    s = settings
    if s is None and rt is not None:
        s = rt.settings
    if s is None:
        s = Settings()

    pid = project_id
    pslug = project_slug
    if pid is None and pslug is None:
        pid = s.project_id
        pslug = s.project_slug
    pid = pid or None
    pslug = pslug or None

    if pid is not None and pslug is not None:
        pslug = None

    if pid is None and pslug is None:
        raise ValueError(
            "Provide project_id or project_slug "
            "(arguments or Settings.project_id / Settings.project_slug)"
        )

    return ResolvedConfig(
        endpoint=endpoint or otlp_endpoint(tracking_uri=s.tracking_uri, runtime=rt),
        service_name=service_name or s.service_name or DEFAULT_SERVICE_NAME,
        project_id=pid,
        project_slug=pslug,
        version=version or s.version or None,
        environment=environment or s.environment or None,
    )


def project_headers(config: ResolvedConfig) -> dict[str, str]:
    if config.project_id:
        return {"X-Project-Id": config.project_id}
    assert config.project_slug is not None
    return {"X-Project-Slug": config.project_slug}
