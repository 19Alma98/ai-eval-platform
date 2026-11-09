from __future__ import annotations

import asyncio
import inspect
import json
import time
from collections.abc import AsyncIterator, Iterator
from types import SimpleNamespace

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

import opengrade
from opengrade import _config, _otel, _trace
from opengrade._config import DEFAULT_MAX_CAPTURE_BYTES
from opengrade._trace import _chunk_text, _default_join_chunks, truncate_value

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


def test_chunk_text_str_and_common_shapes() -> None:
    assert _chunk_text("hi") == "hi"
    assert _chunk_text({"content": "a"}) == "a"
    assert _chunk_text(SimpleNamespace(content="b")) == "b"
    assert _chunk_text({"delta": {"content": "c"}}) == "c"
    assert _chunk_text({"choices": [{"delta": {"content": "d"}}]}) == "d"
    assert _chunk_text(SimpleNamespace(delta=SimpleNamespace(content="e"))) == "e"
    assert _chunk_text({"text": "f"}) == "f"
    assert _chunk_text(SimpleNamespace(text="g")) == "g"
    assert _chunk_text(object()) == ""
    assert _chunk_text({"content": 1}) == ""  # non-str content ignored


def test_default_join_chunks_concat_and_none_acc() -> None:
    assert _default_join_chunks("a", None) == "a"
    assert _default_join_chunks("b", "a") == "ab"
    assert _default_join_chunks({"content": "c"}, "ab") == "abc"


def test_default_join_chunks_respects_byte_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_trace, "max_capture_bytes", lambda: 4)
    # "aaaa" = 4 bytes; next append of "bbbb" would exceed → truncate marker, no further growth
    acc = _default_join_chunks("aaaa", None)
    acc2 = _default_join_chunks("bbbb", acc)
    assert isinstance(acc2, str)
    assert acc2.endswith("…[truncated]") or "…[truncated]" in acc2
    assert len(acc2.encode("utf-8")) <= 8 + len("…[truncated]".encode("utf-8"))
    # further joins are no-ops once truncated
    assert _default_join_chunks("cccc", acc2) == acc2


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


def test_truncate_value_reduces_before_json_dumps(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[object] = []
    real_dumps = json.dumps

    def spy(obj: object, **kwargs: object) -> str:
        seen.append(obj)
        return real_dumps(obj, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(_trace.json, "dumps", spy)
    out = truncate_value({"k": "x" * 10_000}, limit=64)
    assert seen, "json.dumps should still be called"
    reduced = seen[0]
    assert isinstance(reduced, dict)
    assert len(reduced["k"]) < 10_000
    assert len(out.encode("utf-8")) <= 64
    assert out.endswith("…[truncated]") or len(out.encode("utf-8")) <= 64


def test_truncate_value_nested_stops_after_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[object] = []
    real_dumps = json.dumps

    def spy(obj: object, **kwargs: object) -> str:
        seen.append(obj)
        return real_dumps(obj, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(_trace.json, "dumps", spy)
    payload = {"a": "x" * 50, "b": "y" * 50, "c": "z" * 50}
    out = truncate_value(payload, limit=40)
    assert seen, "json.dumps should still be called"
    reduced = seen[0]
    assert isinstance(reduced, dict)
    assert "c" not in reduced  # budget walk must omit late keys, not final clip alone
    if "b" in reduced:
        assert isinstance(reduced["b"], str)
        assert len(reduced["b"]) < 50
    assert len(out.encode("utf-8")) <= 40


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


def test_trace_omits_self_from_input(spans: InMemorySpanExporter) -> None:
    class Greeter:
        @opengrade.trace(name="greet-method")
        def greet(self, name: str) -> str:
            return f"hi {name}"

    assert Greeter().greet("ada") == "hi ada"
    attrs = dict(spans.get_finished_spans()[0].attributes or {})
    payload = json.loads(str(attrs["input.value"]))
    assert "self" not in payload
    assert payload.get("name") == "ada"


def test_trace_omits_cls_from_input(spans: InMemorySpanExporter) -> None:
    class Factory:
        @classmethod
        @opengrade.trace(name="make")
        def make(cls, n: int) -> int:
            return n

    assert Factory.make(3) == 3
    payload = json.loads(str(dict(spans.get_finished_spans()[0].attributes or {})["input.value"]))
    assert "cls" not in payload
    assert payload.get("n") == 3


def test_trace_flat_bound_args_payload(spans: InMemorySpanExporter) -> None:
    @opengrade.trace(name="add")
    def add(a: int, b: int) -> int:
        return a + b

    assert add(1, 2) == 3
    payload = json.loads(str(dict(spans.get_finished_spans()[0].attributes or {})["input.value"]))
    assert payload == {"a": 1, "b": 2}
    assert "args" not in payload and "kwargs" not in payload


def test_trace_decorator_redact_overrides_global(spans: InMemorySpanExporter) -> None:
    _config.configure_capture(redact=lambda n, v: f"global:{v}")
    try:

        @opengrade.trace(name="lookup", redact=lambda n, v: "***" if n == "api_key" else v)
        def lookup(customer_id: str, api_key: str) -> str:
            return customer_id

        lookup("c1", "SECRET")
        payload = json.loads(
            str(dict(spans.get_finished_spans()[0].attributes or {})["input.value"])
        )
        assert payload["customer_id"] == "c1"
        assert payload["api_key"] == "***"
    finally:
        _config.configure_capture()


def test_trace_uses_global_redact_when_decorator_omits(
    spans: InMemorySpanExporter,
) -> None:
    _config.configure_capture(redact=lambda n, v: "***" if n == "token" else v)
    try:

        @opengrade.trace(name="call")
        def call(token: str) -> str:
            return "ok"

        call("abc")
        payload = json.loads(
            str(dict(spans.get_finished_spans()[0].attributes or {})["input.value"])
        )
        assert payload["token"] == "***"
    finally:
        _config.configure_capture()


def test_trace_uses_global_redact_output_when_decorator_omits(
    spans: InMemorySpanExporter,
) -> None:
    _config.configure_capture(redact_output=lambda v: {"masked": True})
    try:

        @opengrade.trace(name="call-out")
        def call() -> dict:
            return {"password": "SECRET"}

        assert call() == {"password": "SECRET"}
        out = json.loads(str(dict(spans.get_finished_spans()[0].attributes or {})["output.value"]))
        assert out == {"masked": True}
    finally:
        _config.configure_capture()


def test_reset_config_overrides_clears_redactors() -> None:
    _config.configure_capture(
        redact=lambda n, v: v,
        redact_output=lambda v: v,
    )
    _config._reset_for_tests()
    assert _config.capture_redact() is None
    assert _config.capture_redact_output() is None


def test_trace_redact_error_placeholder(spans: InMemorySpanExporter) -> None:
    def bad(name: str, value: object) -> object:
        if name == "secret":
            raise RuntimeError("boom")
        return value

    @opengrade.trace(name="x", redact=bad)
    def fn(secret: str, ok: str) -> str:
        return ok

    assert fn("nope", "yes") == "yes"
    payload = json.loads(str(dict(spans.get_finished_spans()[0].attributes or {})["input.value"]))
    assert payload["secret"] == "<redact error>"
    assert payload["ok"] == "yes"


def test_trace_redact_output(spans: InMemorySpanExporter) -> None:
    @opengrade.trace(name="out", redact_output=lambda v: {"masked": True})
    def fn() -> dict:
        return {"password": "x"}

    fn()
    out = json.loads(str(dict(spans.get_finished_spans()[0].attributes or {})["output.value"]))
    assert out == {"masked": True}


def test_trace_redact_output_error_placeholder(spans: InMemorySpanExporter) -> None:
    @opengrade.trace(
        name="out-err", redact_output=lambda v: (_ for _ in ()).throw(RuntimeError("x"))
    )
    def fn() -> str:
        return "secret"

    assert fn() == "secret"
    assert dict(spans.get_finished_spans()[0].attributes or {})["output.value"] == "<redact error>"


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

    def counting_serialize(fn, args, kwargs, *, redact=None) -> str:
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
