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
from opengrade import _config, _otel


@contextmanager
def opengrade_span() -> Iterator[None]:
    with trace.get_tracer("test").start_as_current_span("s"):
        yield


@pytest.fixture(autouse=True)
def reset_otel_state(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv("OPENGRADE_PROJECT_ID", raising=False)
    monkeypatch.delenv("OPENGRADE_PROJECT_SLUG", raising=False)
    monkeypatch.delenv("OPENGRADE_DISABLED", raising=False)
    _config._reset_for_tests()
    _otel._reset_for_tests()
    yield
    _config._reset_for_tests()
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
        self.batch_sizes: list[int] = []

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        self.calls += 1
        self.batch_sizes.append(len(spans))
        if self.raises:
            raise ConnectionError("down")
        return SpanExportResult.FAILURE

    def shutdown(self) -> None:
        pass


class _SizeSensitiveExporter(SpanExporter):
    """Fails batches larger than ``limit`` spans (stands in for HTTP 413)."""

    def __init__(self, *, limit: int) -> None:
        self.limit = limit
        self.calls = 0
        self.exported = 0

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        self.calls += 1
        if len(spans) > self.limit:
            return SpanExportResult.FAILURE
        self.exported += len(spans)
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        pass


@pytest.mark.parametrize("raises", [False, True])
def test_safe_exporter_drops_and_backs_off(raises: bool, caplog: pytest.LogCaptureFixture) -> None:
    inner = _FailingExporter(raises=raises)
    safe = _otel._SafeSpanExporter(inner, cooldown_s=60)
    with caplog.at_level(logging.DEBUG, logger="opengrade"):
        # Single-span failure: drop without cooldown (oversize / reject).
        assert safe.export([object()]) is SpanExportResult.FAILURE  # type: ignore[list-item]
        # Multi-span failure after split: all leaves fail → cooldown.
        assert safe.export([object(), object()]) is SpanExportResult.FAILURE  # type: ignore[list-item]
        assert safe.export([object()]) is SpanExportResult.FAILURE  # type: ignore[list-item]
    # 1 + (2 then 1+1 split) = 4 attempts; third export skipped during cooldown.
    assert inner.calls == 4
    assert safe.dropped_spans == 4  # 1 + 2 leaves + 1 cooldown drop
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1


def test_safe_exporter_splits_oversized_batch_without_cooldown() -> None:
    inner = _SizeSensitiveExporter(limit=1)
    safe = _otel._SafeSpanExporter(inner, cooldown_s=60)
    spans = [object(), object(), object()]  # type: ignore[list-item]
    assert safe.export(spans) is SpanExportResult.SUCCESS
    assert inner.exported == 3
    assert safe.dropped_spans == 0
    # A later export still reaches the network (no cooldown).
    assert safe.export([object()]) is SpanExportResult.SUCCESS  # type: ignore[list-item]
    assert inner.exported == 4


def test_safe_exporter_single_oversize_does_not_cooldown() -> None:
    inner = _FailingExporter()
    safe = _otel._SafeSpanExporter(inner, cooldown_s=60)
    assert safe.export([object()]) is SpanExportResult.FAILURE  # type: ignore[list-item]
    assert safe.dropped_spans == 1
    assert safe.export([object()]) is SpanExportResult.FAILURE  # type: ignore[list-item]
    assert inner.calls == 2  # second attempt still hits the network


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
    assert _otel._OWNS_PROVIDER is True
    assert _otel._INITIALIZED is True


class _RecordingExporter(SpanExporter):
    def __init__(self) -> None:
        self.spans: list[ReadableSpan] = []

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        self.spans.extend(spans)
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        pass


def test_init_attaches_to_existing_host_provider() -> None:
    host = TracerProvider(shutdown_on_exit=False)
    host_exporter = _RecordingExporter()
    host.add_span_processor(_otel.BatchSpanProcessor(host_exporter))
    trace.set_tracer_provider(host)

    opengrade.init(project_slug="demo", instrument=False)

    assert _otel._OWNS_PROVIDER is False
    assert _otel._PROVIDER is host
    assert trace.get_tracer_provider() is host

    with opengrade_span():
        pass
    assert opengrade.flush() is True
    # Spans go through the shared host provider (host + opengrade processors).
    assert any(s.name == "s" for s in host_exporter.spans)


def test_init_force_does_not_shutdown_host_provider() -> None:
    host = TracerProvider(shutdown_on_exit=False)
    trace.set_tracer_provider(host)
    opengrade.init(project_slug="demo", instrument=False)
    opengrade.init(project_slug="demo", instrument=False, force=True)

    assert trace.get_tracer_provider() is host
    assert _otel._OWNS_PROVIDER is False
    # Host provider must still accept spans after force re-init.
    with opengrade_span():
        pass
    opengrade.flush()  # may fail export to unreachable OTLP; must not raise


def test_at_exit_does_not_shutdown_host_provider() -> None:
    host = TracerProvider(shutdown_on_exit=False)
    trace.set_tracer_provider(host)
    opengrade.init(project_slug="demo", instrument=False)
    _otel._at_exit()

    assert trace.get_tracer_provider() is host
    assert _otel._PROVIDER is None
    assert _otel._OWNS_PROVIDER is False
    with opengrade_span():
        pass


def test_init_honors_service_name_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENGRADE_SERVICE_NAME", "env-svc")
    opengrade.init(project_slug="demo", instrument=False)
    provider = _otel._PROVIDER
    assert isinstance(provider, TracerProvider)
    assert provider.resource.attributes.get("service.name") == "env-svc"


def test_init_sets_release_resource(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENGRADE_ENVIRONMENT", "prod")
    opengrade.init(project_slug="demo", instrument=False, version="1.4.2")
    provider = _otel._PROVIDER
    assert isinstance(provider, TracerProvider)
    attrs = provider.resource.attributes
    assert attrs.get("service.version") == "1.4.2"
    assert attrs.get("deployment.environment") == "prod"
    assert "opengrade.version" not in attrs


def test_init_on_host_provider_stamps_release_on_spans() -> None:
    host = TracerProvider(shutdown_on_exit=False)
    host_exporter = _RecordingExporter()
    host.add_span_processor(_otel.BatchSpanProcessor(host_exporter))
    trace.set_tracer_provider(host)

    opengrade.init(project_slug="demo", instrument=False, version="v9", environment="staging")
    with opengrade_span():
        pass
    opengrade.flush()
    host.force_flush()
    (span,) = [s for s in host_exporter.spans if s.name == "s"]
    assert span.attributes is not None
    assert span.attributes["opengrade.version"] == "v9"
    assert span.attributes["opengrade.environment"] == "staging"


def test_flush_without_init_returns_true() -> None:
    assert opengrade.flush() is True


def test_otlp_exporter_not_imported_until_init(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cold-start path: importing opengrade / calling is_disabled must not load protobuf OTLP."""
    import sys

    monkeypatch.setenv("OPENGRADE_DISABLED", "1")
    doomed = [name for name in sys.modules if "opentelemetry.exporter.otlp" in name]
    for name in doomed:
        del sys.modules[name]

    assert opengrade._otel.is_disabled()
    assert not any("opentelemetry.exporter.otlp" in name for name in sys.modules)

    opengrade.init(project_slug="demo", instrument=False)
    assert not any("opentelemetry.exporter.otlp" in name for name in sys.modules)


def test_package_import_defers_httpx_and_otlp() -> None:
    """Documented cold-start graph: ``import opengrade`` leaves heavy deps unloaded.

    Runs in a subprocess so earlier tests cannot have already imported the modules.
    """
    import subprocess
    import sys

    script = """
import sys
import opengrade
assert opengrade.trace is not None
assert "httpx2" not in sys.modules
assert "pydantic" not in sys.modules
assert not any("opentelemetry.exporter.otlp" in m for m in sys.modules)
assert "opengrade.client" not in sys.modules
assert "opengrade.experiment" not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-c", script], check=False, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
