from __future__ import annotations

import asyncio

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

import aiobs
from aiobs._config import MAX_CAPTURE_BYTES
from aiobs._trace import truncate_value

_shared_exporter: InMemorySpanExporter | None = None


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
    @aiobs.trace
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
    @aiobs.trace(name="faq", kind="CHAIN", capture_input=False, capture_output=False)
    def answer(q: str) -> str:
        return "ok"

    answer("q")
    span = spans.get_finished_spans()[0]
    attrs = dict(span.attributes or {})
    assert span.name == "faq"
    assert "input.value" not in attrs
    assert "output.value" not in attrs


def test_trace_reraises_and_records_exception(spans: InMemorySpanExporter) -> None:
    @aiobs.trace
    def boom() -> None:
        raise RuntimeError("nope")

    with pytest.raises(RuntimeError, match="nope"):
        boom()
    span = spans.get_finished_spans()[0]
    assert span.status.status_code == StatusCode.ERROR


def test_trace_async(spans: InMemorySpanExporter) -> None:
    @aiobs.trace_async(name="async-faq")
    async def ask(q: str) -> str:
        return "pong"

    assert asyncio.run(ask("ping")) == "pong"
    span = spans.get_finished_spans()[0]
    assert span.name == "async-faq"
    assert dict(span.attributes or {})["openinference.span.kind"] == "CHAIN"
