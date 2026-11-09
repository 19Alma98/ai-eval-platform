from __future__ import annotations

import asyncio
import inspect
import time
from collections.abc import AsyncIterator, Iterator

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

import opengrade
from opengrade import _config, _otel
from opengrade._config import DEFAULT_MAX_CAPTURE_BYTES
from opengrade._trace import truncate_value

_shared_exporter: InMemorySpanExporter | None = None


@pytest.fixture(scope="module", autouse=True)
def _reset_otel_before_trace_tests() -> Iterator[None]:
    global _shared_exporter
    _otel._reset_for_tests()
    _shared_exporter = None
    yield
    _shared_exporter = None
    _otel._reset_for_tests()


@pytest.fixture
def spans() -> InMemorySpanExporter:
    global _shared_exporter
    if _shared_exporter is None:
        _shared_exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(_shared_exporter))
        trace.set_tracer_provider(provider)
    else:
        _shared_exporter.clear()
    return _shared_exporter


def test_truncate_value_adds_marker() -> None:
    big = "x" * (DEFAULT_MAX_CAPTURE_BYTES + 10)
    out = truncate_value(big)
    assert len(out.encode("utf-8")) <= DEFAULT_MAX_CAPTURE_BYTES
    assert out.endswith("…[truncated]")


def test_truncate_value_honors_configured_limit() -> None:
    _config.configure_capture(max_capture_bytes=32)
    try:
        out = truncate_value("x" * 100)
        assert len(out.encode("utf-8")) <= 32
        assert out.endswith("…[truncated]")
    finally:
        _config.configure_capture()


def test_configure_capture_redact_roundtrip() -> None:
    def hide(name: str, value: object) -> object:
        return "***" if name == "api_key" else value

    def hide_out(value: object) -> object:
        return {"redacted": True}

    _config.configure_capture(redact=hide, redact_output=hide_out)
    try:
        assert _config.capture_redact() is hide
        assert _config.capture_redact_output() is hide_out
        _config.configure_capture(redact=None)
        assert _config.capture_redact() is None
        assert _config.capture_redact_output() is hide_out
    finally:
        _config.configure_capture()


def test_configure_capture_empty_resets_redactors_and_limit() -> None:
    _config.configure_capture(
        max_capture_bytes=64,
        redact=lambda n, v: v,
        redact_output=lambda v: v,
    )
    _config.configure_capture()
    assert _config.capture_redact() is None
    assert _config.capture_redact_output() is None
    # byte override cleared → default (env or DEFAULT)
    assert _config.max_capture_bytes() == DEFAULT_MAX_CAPTURE_BYTES


def test_configure_capture_partial_preserves_other_fields() -> None:
    def hide(name: str, value: object) -> object:
        return value

    _config.configure_capture(max_capture_bytes=128, redact=hide)
    try:
        _config.configure_capture(max_capture_bytes=256)
        assert _config.max_capture_bytes() == 256
        assert _config.capture_redact() is hide
    finally:
        _config.configure_capture()


def test_configure_capture_exported_on_opengrade() -> None:
    assert opengrade.configure_capture is _config.configure_capture


def test_trace_sets_kind_input_output(spans: InMemorySpanExporter) -> None:
    @opengrade.trace
    def greet(name: str) -> str:
        return f"hi {name}"

    assert greet("ada") == "hi ada"
    exported = spans.get_finished_spans()
    assert len(exported) == 1
    span = exported[0]
    attrs = dict(span.attributes or {})
    assert attrs["openinference.span.kind"] == "CHAIN"
    assert "ada" in str(attrs.get("input.value", ""))
    assert attrs.get("output.value") == "hi ada"
    assert span.name.endswith("greet")


def test_trace_with_explicit_name(spans: InMemorySpanExporter) -> None:
    @opengrade.trace(name="faq", kind="CHAIN", capture_input=False, capture_output=False)
    def answer(q: str) -> str:
        return "ok"

    answer("q")
    span = spans.get_finished_spans()[0]
    attrs = dict(span.attributes or {})
    assert span.name == "faq"
    assert "input.value" not in attrs
    assert "output.value" not in attrs


def test_trace_reraises_and_records_exception(spans: InMemorySpanExporter) -> None:
    @opengrade.trace
    def boom() -> None:
        raise RuntimeError("nope")

    with pytest.raises(RuntimeError, match="nope"):
        boom()
    span = spans.get_finished_spans()[0]
    assert span.status.status_code == StatusCode.ERROR
    exception_events = [e for e in span.events if e.name == "exception"]
    assert len(exception_events) == 1


def test_trace_on_async_def_preserves_coroutine(spans: InMemorySpanExporter) -> None:
    @opengrade.trace(name="async-via-trace")
    async def ask(q: str) -> str:
        return "pong"

    assert inspect.iscoroutinefunction(ask)
    assert asyncio.run(ask("ping")) == "pong"
    span = spans.get_finished_spans()[0]
    assert span.name == "async-via-trace"
    assert dict(span.attributes or {})["output.value"] == "pong"


def test_trace_sync_generator_keeps_span_open(spans: InMemorySpanExporter) -> None:
    @opengrade.trace(name="stream")
    def tokens() -> Iterator[str]:
        yield "a"
        time.sleep(0.02)
        yield "b"

    assert inspect.isgeneratorfunction(tokens)
    assert list(tokens()) == ["a", "b"]
    span = spans.get_finished_spans()[0]
    assert span.name == "stream"
    assert span.end_time - span.start_time >= 15_000_000  # >= 15ms in ns
    assert dict(span.attributes or {})["output.value"] == '["a", "b"]'


def test_trace_async_generator(spans: InMemorySpanExporter) -> None:
    @opengrade.trace(name="astream")
    async def tokens() -> AsyncIterator[str]:
        yield "x"
        yield "y"

    assert inspect.isasyncgenfunction(tokens)

    async def main() -> list[str]:
        return [item async for item in tokens()]

    assert asyncio.run(main()) == ["x", "y"]
    span = spans.get_finished_spans()[0]
    assert span.name == "astream"
    assert dict(span.attributes or {})["output.value"] == '["x", "y"]'


def test_span_helpers_set_io_attrs_and_trace_id(spans: InMemorySpanExporter) -> None:
    seen: dict[str, str | None] = {}

    @opengrade.trace(name="helpers", capture_input=False, capture_output=False)
    def run(q: str) -> str:
        opengrade.set_input(q)
        opengrade.set_attribute("rag.mode", "good")
        opengrade.set_attributes({"retrieval.document_count": 2})
        opengrade.set_output("done")
        seen["trace_id"] = opengrade.current_trace_id()
        return "ignored"

    assert run("ping") == "ignored"
    span = spans.get_finished_spans()[0]
    attrs = dict(span.attributes or {})
    assert attrs["input.value"] == "ping"
    assert attrs["output.value"] == "done"
    assert attrs["rag.mode"] == "good"
    assert attrs["retrieval.document_count"] == 2
    assert seen["trace_id"] == format(span.context.trace_id, "032x")


def test_attr_value_stringifies_ints_outside_int64() -> None:
    from opengrade._trace import _attr_value

    assert _attr_value(2**63) == str(2**63)
    assert _attr_value(-(2**63) - 1) == str(-(2**63) - 1)
    assert _attr_value(2**63 - 1) == 2**63 - 1
    assert _attr_value(-(2**63)) == -(2**63)
    assert _attr_value(True) is True


def test_set_error_marks_span(spans: InMemorySpanExporter) -> None:
    @opengrade.trace(name="err", capture_input=False, capture_output=False)
    def run() -> None:
        opengrade.set_error("no documents")

    run()
    span = spans.get_finished_spans()[0]
    assert span.status.status_code == StatusCode.ERROR
    assert span.status.description == "no documents"


def test_skips_serialize_when_not_recording(monkeypatch: pytest.MonkeyPatch) -> None:
    from contextlib import contextmanager
    from unittest.mock import MagicMock

    from opengrade import _trace

    serialize_calls: list[object] = []
    truncate_calls: list[object] = []

    def counting_serialize(args: tuple, kwargs: dict) -> str:
        serialize_calls.append((args, kwargs))
        return "{}"

    def counting_truncate(value: object, *, limit: int | None = None) -> str:
        truncate_calls.append(value)
        return "x"

    monkeypatch.setattr(_trace, "_serialize_args", counting_serialize)
    monkeypatch.setattr(_trace, "truncate_value", counting_truncate)

    @contextmanager
    def non_recording_span(_name: str, **_kwargs: object):
        span = MagicMock()
        span.is_recording.return_value = False
        yield span

    class _Tracer:
        def start_as_current_span(self, name: str, **kwargs: object):
            return non_recording_span(name, **kwargs)

    monkeypatch.setattr(_trace.otel_trace, "get_tracer", lambda _name: _Tracer())

    @opengrade.trace(name="quiet")
    def greet(name: str) -> str:
        return f"hi {name}"

    assert greet("ada") == "hi ada"
    assert serialize_calls == []
    assert truncate_calls == []
