"""FastAPI native telemetry: OTLP ingest is never traced, the embedded server is silent."""

from __future__ import annotations

import inspect

import pytest
from fastapi import FastAPI

from opengrade_server.main import _is_otlp_ingest, _telemetry_kwargs, create_app

pytestmark = pytest.mark.skipif(
    "telemetry" not in inspect.signature(FastAPI.__init__).parameters,
    reason="FastAPI without native telemetry",
)


def test_otlp_ingest_is_excluded_from_server_spans() -> None:
    kwargs = _telemetry_kwargs(self_telemetry=True)
    exclude = kwargs["telemetry"]["exclude"]
    assert exclude is _is_otlp_ingest
    assert exclude({"type": "http", "path": "/v1/traces"})
    assert not exclude({"type": "http", "path": "/api/v1/projects"})


def test_embedded_server_disables_its_own_telemetry() -> None:
    telemetry = _telemetry_kwargs(self_telemetry=False)["telemetry"]
    assert telemetry["tracing"] is False
    assert telemetry["operation_spans"] is False
    assert telemetry["auto_configure"] is False
    app = create_app(mount_packaged_ui=False, self_telemetry=False)
    assert app._telemetry["tracing"] is False  # type: ignore[attr-defined]
