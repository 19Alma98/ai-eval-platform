from __future__ import annotations

import logging
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from tests.support.instance import init_og, make_og

import opengrade
from opengrade import Opengrade, Settings, _config, _otel


@contextmanager
def opengrade_span() -> Iterator[None]:
    with trace.get_tracer("test").start_as_current_span("s"):
        yield


@pytest.fixture(autouse=True)
def reset_otel_state(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv("OPENGRADE_PROJECT_ID", raising=False)
    monkeypatch.delenv("OPENGRADE_PROJECT_SLUG", raising=False)
    monkeypatch.delenv("OPENGRADE_DISABLED", raising=False)
    monkeypatch.delenv("OPENGRADE_TRACE_SAMPLE_RATE", raising=False)
    monkeypatch.delenv("OPENGRADE_MAX_CAPTURE_BYTES", raising=False)
    from tests.support.reset import reset_sdk

    reset_sdk(otel=True)
    yield
    reset_sdk(otel=True)


def test_init_without_project_warns_and_is_noop(caplog: pytest.LogCaptureFixture) -> None:
    og = make_og()
    with caplog.at_level(logging.WARNING, logger="opengrade"):
        og.init_tracing()
    assert _otel._PROVIDER is None
    assert _otel._INITIALIZED is False
    assert any("tracing disabled" in r.message for r in caplog.records)
    assert og.flush() is True


def test_init_noop_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENGRADE_DISABLED", "true")
    init_og(project_slug="demo", instrument=False)
    assert _otel._PROVIDER is None
    assert _otel._INITIALIZED is False


def test_init_unknown_instrumentor_keeps_tracing(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="opengrade"):
        init_og(project_slug="demo", instrument=["nope"])
    assert _otel._INITIALIZED is True
    assert any("auto-instrumentation skipped" in r.message for r in caplog.records)


def test_init_registers_atexit_flush(monkeypatch: pytest.MonkeyPatch) -> None:
    registered: list[object] = []
    monkeypatch.setattr(_otel, "_ATEXIT_REGISTERED", False)
    monkeypatch.setattr(_otel.atexit, "register", registered.append)
    og = init_og(project_slug="demo", instrument=False)
    og.init_tracing(project_slug="demo", instrument=False, force=True)
    assert registered == [_otel._at_exit]


def test_at_exit_with_unreachable_server_is_fast_and_silent(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Nothing listens on port 9: connection refused.
    _ = init_og(project_slug="demo", endpoint="http://127.0.0.1:9/v1/traces", instrument=False)
    with opengrade_span():
        pass
    start = time.monotonic()
    with caplog.at_level(logging.DEBUG):
        _otel._at_exit()
    assert time.monotonic() - start < _otel.EXPORT_TIMEOUT_S + 1
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


class _FailingExporter(SpanExporter):
    """Always fails. Optional HTTP status (default 503) — not a size error."""

    def __init__(self, *, raises: bool = False, status: int | None = 503) -> None:
        self.calls = 0
        self.raises = raises
        self.status = status
        self.last_export_status: int | None = None
        self.batch_sizes: list[int] = []

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        self.calls += 1
        self.batch_sizes.append(len(spans))
        self.last_export_status = None if self.raises else self.status
        if self.raises:
            raise ConnectionError("down")
        return SpanExportResult.FAILURE

    def shutdown(self) -> None:
        pass


class _SizeSensitiveExporter(SpanExporter):
    """Fails batches larger than ``limit`` spans with HTTP 413."""

    def __init__(self, *, limit: int, status: int = 413) -> None:
        self.limit = limit
        self.status = status
        self.calls = 0
        self.exported = 0
        self.last_export_status: int | None = None

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        self.calls += 1
        if len(spans) > self.limit:
            self.last_export_status = self.status
            return SpanExportResult.FAILURE
        self.last_export_status = 200
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
        # Multi-span 5xx / connection failure: no bisect → cooldown immediately.
        assert safe.export([object(), object()]) is SpanExportResult.FAILURE  # type: ignore[list-item]
        assert safe.export([object()]) is SpanExportResult.FAILURE  # type: ignore[list-item]
    # 1 single + 1 multi (no split); third export skipped during cooldown.
    assert inner.calls == 2
    assert inner.batch_sizes == [1, 2]
    assert safe.dropped_spans == 4  # 1 + 2 + 1 cooldown drop
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1


def test_safe_exporter_does_not_split_on_server_errors() -> None:
    inner = _FailingExporter(status=503)
    safe = _otel._SafeSpanExporter(inner, cooldown_s=60)
    spans = [object()] * 8  # type: ignore[list-item]
    assert safe.export(spans) is SpanExportResult.FAILURE
    assert inner.calls == 1
    assert inner.batch_sizes == [8]
    assert safe.dropped_spans == 8
    # Cooldown: next batch is dropped without a network call.
    assert safe.export([object()]) is SpanExportResult.FAILURE  # type: ignore[list-item]
    assert inner.calls == 1


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


@pytest.mark.parametrize("status", [413, 400])
def test_safe_exporter_splits_on_size_http_status(status: int) -> None:
    inner = _SizeSensitiveExporter(limit=1, status=status)
    safe = _otel._SafeSpanExporter(inner, cooldown_s=60)
    spans = [object(), object()]  # type: ignore[list-item]
    assert safe.export(spans) is SpanExportResult.SUCCESS
    assert inner.exported == 2
    assert inner.calls >= 3  # full batch + two halves


def test_safe_exporter_aborts_size_split_at_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_otel, "EXPORT_TIMEOUT_S", 0.05)

    class _SlowSizeExporter(SpanExporter):
        def __init__(self) -> None:
            self.calls = 0
            self.last_export_status: int | None = None

        def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
            self.calls += 1
            time.sleep(0.04)
            self.last_export_status = 413
            return SpanExportResult.FAILURE

        def shutdown(self) -> None:
            pass

    inner = _SlowSizeExporter()
    safe = _otel._SafeSpanExporter(inner, cooldown_s=60)
    spans = [object()] * 16  # type: ignore[list-item]
    start = time.monotonic()
    assert safe.export(spans) is SpanExportResult.FAILURE
    elapsed = time.monotonic() - start
    # Without a deadline this would be 31 slow attempts (~1.2s+).
    assert elapsed < 0.4
    assert inner.calls < 8


def test_safe_exporter_single_oversize_does_not_cooldown() -> None:
    # Unknown / non-size single-span reject: drop, keep trying later batches.
    inner = _FailingExporter(status=400)
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
    _ = init_og(project_slug="demo", instrument=False)
    provider = _otel._PROVIDER
    assert isinstance(provider, TracerProvider)
    assert _otel._INITIALIZED is True


def test_init_idempotent_without_force(caplog: pytest.LogCaptureFixture) -> None:
    og = init_og(project_slug="demo", instrument=False)
    first = _otel._PROVIDER
    with caplog.at_level(logging.INFO, logger="opengrade"):
        og.init_tracing(instrument=False)
    assert _otel._PROVIDER is first


def test_init_force_reconfigures(monkeypatch: pytest.MonkeyPatch) -> None:
    og = init_og(project_slug="demo", instrument=False)
    og.init_tracing(instrument=False, force=True)
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

    og = init_og(project_slug="demo", instrument=False)

    assert _otel._OWNS_PROVIDER is False
    assert _otel._PROVIDER is host
    assert trace.get_tracer_provider() is host

    with opengrade_span():
        pass
    assert og.flush() is True
    # Spans go through the shared host provider (host + opengrade processors).
    assert any(s.name == "s" for s in host_exporter.spans)


def test_init_force_does_not_shutdown_host_provider() -> None:
    host = TracerProvider(shutdown_on_exit=False)
    trace.set_tracer_provider(host)
    og = init_og(project_slug="demo", instrument=False)
    og.init_tracing(instrument=False, force=True)

    assert trace.get_tracer_provider() is host
    assert _otel._OWNS_PROVIDER is False
    # Host provider must still accept spans after force re-init.
    with opengrade_span():
        pass
    og.flush()  # may fail export to unreachable OTLP; must not raise


def test_at_exit_does_not_shutdown_host_provider() -> None:
    host = TracerProvider(shutdown_on_exit=False)
    trace.set_tracer_provider(host)
    _ = init_og(project_slug="demo", instrument=False)
    _otel._at_exit()

    assert trace.get_tracer_provider() is host
    assert _otel._PROVIDER is host
    assert _otel._OWNS_PROVIDER is False
    with opengrade_span():
        pass


def test_init_honors_service_name_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENGRADE_SERVICE_NAME", "env-svc")
    og = Opengrade(Settings.from_env(project_slug="demo"))
    og.init_tracing(instrument=False)
    provider = _otel._PROVIDER
    assert isinstance(provider, TracerProvider)
    assert provider.resource.attributes.get("service.name") == "env-svc"


def test_init_sets_release_resource(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENGRADE_ENVIRONMENT", "prod")
    og = Opengrade(Settings.from_env(project_slug="demo"))
    og.init_tracing(instrument=False, version="1.4.2")
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

    og = init_og(project_slug="demo", instrument=False, version="v9", environment="staging")
    with og.activate():
        with opengrade_span():
            pass
    og.flush()
    host.force_flush()
    (span,) = [s for s in host_exporter.spans if s.name == "s"]
    assert span.attributes is not None
    assert span.attributes["opengrade.version"] == "v9"
    assert span.attributes["opengrade.environment"] == "staging"


def test_flush_without_init_returns_true() -> None:
    og = make_og(project_slug="demo")
    assert og.flush() is True


def test_otlp_exporter_not_imported_until_init(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cold-start path: importing opengrade / calling is_disabled must not load protobuf OTLP."""
    import sys

    monkeypatch.setenv("OPENGRADE_DISABLED", "1")
    doomed = [name for name in sys.modules if "opentelemetry.exporter.otlp" in name]
    for name in doomed:
        del sys.modules[name]

    assert opengrade._otel.is_disabled()
    assert not any("opentelemetry.exporter.otlp" in name for name in sys.modules)

    _ = init_og(project_slug="demo", instrument=False)
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


def test_init_sets_trace_id_ratio_sampler() -> None:
    from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

    _ = init_og(project_slug="demo", instrument=False, trace_sample_rate=0.25)
    provider = _otel._PROVIDER
    assert isinstance(provider, TracerProvider)
    assert isinstance(provider.sampler, ParentBased)
    assert isinstance(provider.sampler._root, TraceIdRatioBased)
    assert provider.sampler._root._rate == 0.25


def test_init_trace_sample_rate_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from opentelemetry.sdk.trace.sampling import TraceIdRatioBased

    monkeypatch.setenv("OPENGRADE_TRACE_SAMPLE_RATE", "0.5")
    _ = init_og(project_slug="demo", instrument=False)
    provider = _otel._PROVIDER
    assert isinstance(provider, TracerProvider)
    assert isinstance(provider.sampler._root, TraceIdRatioBased)
    assert provider.sampler._root._rate == 0.5


def test_init_does_not_replace_host_sampler() -> None:
    from opentelemetry.sdk.trace.sampling import ALWAYS_ON, StaticSampler

    host = TracerProvider(sampler=ALWAYS_ON, shutdown_on_exit=False)
    trace.set_tracer_provider(host)
    _ = init_og(project_slug="demo", instrument=False, trace_sample_rate=0.1)
    assert trace.get_tracer_provider() is host
    assert isinstance(host.sampler, StaticSampler)


def test_init_max_capture_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.support.instance import activated
    from tests.support.reset import reset_sdk

    og = init_og(project_slug="demo", instrument=False, max_capture_bytes=128)
    with activated(og):
        assert _config.max_capture_bytes() == 128

    reset_sdk(otel=True)
    monkeypatch.setenv("OPENGRADE_MAX_CAPTURE_BYTES", "256")
    og_env = Opengrade(Settings.from_env(project_slug="demo"))
    og_env.init_tracing(instrument=False)
    with activated(og_env):
        assert _config.max_capture_bytes() == 256


def test_resolve_trace_sample_rate_rejects_out_of_range() -> None:
    with pytest.raises(ValueError, match="trace_sample_rate"):
        _otel.resolve_trace_sample_rate(1.5)
