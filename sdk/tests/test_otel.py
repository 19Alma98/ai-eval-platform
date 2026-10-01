from __future__ import annotations

import logging

import pytest
from opentelemetry.sdk.trace import TracerProvider

import aiobs
from aiobs import _otel


@pytest.fixture(autouse=True)
def reset_otel_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AIOBS_PROJECT_ID", raising=False)
    monkeypatch.delenv("AIOBS_PROJECT_SLUG", raising=False)
    _otel._reset_for_tests()
    yield
    _otel._reset_for_tests()


def test_init_requires_project(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="exactly one"):
        aiobs.init()


def test_init_sets_tracer_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    aiobs.init(project_slug="demo", instrument=False)
    provider = _otel._PROVIDER
    assert isinstance(provider, TracerProvider)
    assert _otel._INITIALIZED is True


def test_init_idempotent_without_force(caplog: pytest.LogCaptureFixture) -> None:
    aiobs.init(project_slug="demo", instrument=False)
    first = _otel._PROVIDER
    with caplog.at_level(logging.INFO, logger="aiobs"):
        aiobs.init(project_slug="other", instrument=False)
    assert _otel._PROVIDER is first
    assert any("already initialized" in r.message for r in caplog.records)


def test_init_force_reconfigures(monkeypatch: pytest.MonkeyPatch) -> None:
    aiobs.init(project_slug="demo", instrument=False)
    aiobs.init(project_slug="demo", instrument=False, force=True)
    assert isinstance(_otel._PROVIDER, TracerProvider)
    assert _otel._INITIALIZED is True


def test_flush_without_init_returns_true() -> None:
    assert aiobs.flush() is True
