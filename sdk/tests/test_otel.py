from __future__ import annotations

import logging
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

import opengrade
from opengrade import _otel


@contextmanager
def opengrade_span() -> Iterator[None]:
    with trace.get_tracer("test").start_as_current_span("s"):
        yield


@pytest.fixture(autouse=True)
def reset_otel_state(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv("OPENGRADE_PROJECT_ID", raising=False)
    monkeypatch.delenv("OPENGRADE_PROJECT_SLUG", raising=False)
    monkeypatch.delenv("OPENGRADE_DISABLED", raising=False)
    _otel._reset_for_tests()
    yield
    _otel._reset_for_tests()


def test_init_without_project_warns_and_is_noop(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="opengrade"):
        opengrade.init()
    assert _otel._PROVIDER is None
    assert _otel._INITIALIZED is False
    assert any("tracing disabled" in r.message for r in caplog.records)
    assert opengrade.flush() is True


def test_init_noop_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENGRADE_DISABLED", "true")
    opengrade.init(project_slug="demo", instrument=False)
    assert _otel._PROVIDER is None
    assert _otel._INITIALIZED is False


def test_init_unknown_instrumentor_keeps_tracing(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="opengrade"):
        opengrade.init(project_slug="demo", instrument=["nope"])
    assert _otel._INITIALIZED is True
    assert any("auto-instrumentation skipped" in r.message for r in caplog.records)


def test_init_registers_atexit_flush(monkeypatch: pytest.MonkeyPatch) -> None:
    registered: list[object] = []
    monkeypatch.setattr(_otel, "_ATEXIT_REGISTERED", False)
    monkeypatch.setattr(_otel.atexit, "register", registered.append)
    opengrade.init(project_slug="demo", instrument=False)
    opengrade.init(project_slug="demo", instrument=False, force=True)
    assert registered == [_otel._at_exit]


def test_at_exit_with_unreachable_server_is_fast_and_silent(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Nothing listens on port 9: connection refused.
    opengrade.init(project_slug="demo", endpoint="http://127.0.0.1:9/v1/traces", instrument=False)
    with opengrade_span():
        pass
    start = time.monotonic()
    with caplog.at_level(logging.DEBUG):
        _otel._at_exit()
    assert time.monotonic() - start < _otel.EXPORT_TIMEOUT_S + 1
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


class _FailingExporter(SpanExporter):
    def __init__(self, *, raises: bool = False) -> None:
        self.calls = 0
        self.raises = raises

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        self.calls += 1
        if self.raises:
            raise ConnectionError("down")
        return SpanExportResult.FAILURE

    def shutdown(self) -> None:
        pass


@pytest.mark.parametrize("raises", [False, True])
def test_safe_exporter_drops_and_backs_off(raises: bool, caplog: pytest.LogCaptureFixture) -> None:
    inner = _FailingExporter(raises=raises)
    safe = _otel._SafeSpanExporter(inner, cooldown_s=60)
    with caplog.at_level(logging.DEBUG, logger="opengrade"):
        assert safe.export([object()]) is SpanExportResult.FAILURE  # type: ignore[list-item]
        assert safe.export([object(), object()]) is SpanExportResult.FAILURE  # type: ignore[list-item]
    assert inner.calls == 1  # second batch dropped during cooldown, no network call
    assert safe.dropped_spans == 3
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1


def test_safe_exporter_drops_after_close() -> None:
    inner = _FailingExporter()
    safe = _otel._SafeSpanExporter(inner)
    safe.close()
    assert safe.export([object()]) is SpanExportResult.FAILURE  # type: ignore[list-item]
    assert inner.calls == 0


def test_init_sets_tracer_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    opengrade.init(project_slug="demo", instrument=False)
    provider = _otel._PROVIDER
    assert isinstance(provider, TracerProvider)
    assert _otel._INITIALIZED is True


def test_init_idempotent_without_force(caplog: pytest.LogCaptureFixture) -> None:
    opengrade.init(project_slug="demo", instrument=False)
    first = _otel._PROVIDER
    with caplog.at_level(logging.INFO, logger="opengrade"):
        opengrade.init(project_slug="other", instrument=False)
    assert _otel._PROVIDER is first
    assert any("already initialized" in r.message for r in caplog.records)


def test_init_force_reconfigures(monkeypatch: pytest.MonkeyPatch) -> None:
    opengrade.init(project_slug="demo", instrument=False)
    opengrade.init(project_slug="demo", instrument=False, force=True)
    assert isinstance(_otel._PROVIDER, TracerProvider)
    assert trace.get_tracer_provider() is _otel._PROVIDER
    assert _otel._INITIALIZED is True


def test_init_honors_service_name_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENGRADE_SERVICE_NAME", "env-svc")
    opengrade.init(project_slug="demo", instrument=False)
    provider = _otel._PROVIDER
    assert isinstance(provider, TracerProvider)
    assert provider.resource.attributes.get("service.name") == "env-svc"


def test_flush_without_init_returns_true() -> None:
    assert opengrade.flush() is True
