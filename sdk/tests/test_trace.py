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
from opengrade import _otel
from opengrade._config import MAX_CAPTURE_BYTES
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
    big = "x" * (MAX_CAPTURE_BYTES + 10)
    out = truncate_value(big)
    assert len(out.encode("utf-8")) <= MAX_CAPTURE_BYTES
    assert out.endswith("…[truncated]")


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


def test_trace_async(spans: InMemorySpanExporter) -> None:
    @opengrade.trace_async(name="async-faq")
    async def ask(q: str) -> str:
        return "pong"

    assert asyncio.run(ask("ping")) == "pong"
    span = spans.get_finished_spans()[0]
    assert span.name == "async-faq"
    assert dict(span.attributes or {})["openinference.span.kind"] == "CHAIN"


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


def test_trace_async_on_async_generator(spans: InMemorySpanExporter) -> None:
    @opengrade.trace_async(name="astream2")
    async def tokens() -> AsyncIterator[str]:
        yield "z"

    assert inspect.isasyncgenfunction(tokens)

    async def main() -> list[str]:
        return [item async for item in tokens()]

    assert asyncio.run(main()) == ["z"]
    assert spans.get_finished_spans()[0].name == "astream2"


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

    def counting_truncate(value: object, *, limit: int = MAX_CAPTURE_BYTES) -> str:
        truncate_calls.append(value)
        return "x"

    monkeypatch.setattr(_trace, "_serialize_args", counting_serialize)
    monkeypatch.setattr(_trace, "truncate_value", counting_truncate)

    @contextmanager
    def non_recording_span(_name: str):
        span = MagicMock()
        span.is_recording.return_value = False
        yield span

    class _Tracer:
        def start_as_current_span(self, name: str):
            return non_recording_span(name)

    monkeypatch.setattr(_trace.otel_trace, "get_tracer", lambda _name: _Tracer())

    @opengrade.trace(name="quiet")
    def greet(name: str) -> str:
        return f"hi {name}"

    assert greet("ada") == "hi ada"
    assert serialize_calls == []
    assert truncate_calls == []
