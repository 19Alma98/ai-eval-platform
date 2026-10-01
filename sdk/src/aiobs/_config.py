from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_ENDPOINT = "http://localhost:8000/v1/traces"
DEFAULT_SERVICE_NAME = "aiobs-app"
MAX_CAPTURE_BYTES = 32 * 1024


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
    pid = project_id if project_id is not None else os.getenv("AIOBS_PROJECT_ID")
    pslug = project_slug if project_slug is not None else os.getenv("AIOBS_PROJECT_SLUG")
    # Treat empty strings as unset
    pid = pid or None
    pslug = pslug or None

    if (pid is None) == (pslug is None):
        raise ValueError(
            "Provide exactly one of project_id / project_slug "
            "(arguments or AIOBS_PROJECT_ID / AIOBS_PROJECT_SLUG)"
        )

    return ResolvedConfig(
        endpoint=endpoint or os.getenv("AIOBS_OTLP_ENDPOINT") or DEFAULT_ENDPOINT,
        service_name=service_name or os.getenv("AIOBS_SERVICE_NAME") or DEFAULT_SERVICE_NAME,
        project_id=pid,
        project_slug=pslug,
    )


def project_headers(config: ResolvedConfig) -> dict[str, str]:
    if config.project_id:
        return {"X-Project-Id": config.project_id}
    assert config.project_slug is not None
    return {"X-Project-Slug": config.project_slug}
