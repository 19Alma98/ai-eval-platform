from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode
from tests.support.instance import activated, init_og
from tests.support.reset import reset_sdk

import opengrade
from opengrade import Opengrade

_og: Opengrade | None = None
_exporter: InMemorySpanExporter | None = None


@pytest.fixture(scope="module", autouse=True)
def _reset_otel() -> Iterator[None]:
    global _og, _exporter
    reset_sdk(otel=True)
    _og = None
    _exporter = None
    yield
    _og = None
    _exporter = None
    reset_sdk(otel=True)


@pytest.fixture
def spans(monkeypatch: pytest.MonkeyPatch) -> Iterator[InMemorySpanExporter]:
    global _og, _exporter
    if _exporter is None:
        _exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(_exporter))
        trace.set_tracer_provider(provider)
        monkeypatch.setenv("OPENGRADE_PROJECT_ID", "p-span-attrs")
        _og = init_og(project_id="p-span-attrs", instrument=False, _span_exporter=_exporter)
    else:
        _exporter.clear()
    assert _og is not None
    with activated(_og):
        yield _exporter


def _by_name(exporter: InMemorySpanExporter) -> dict[str, ReadableSpan]:
    return {s.name: s for s in exporter.get_finished_spans()}


def test_span_is_child_with_kind_io_and_attributes(spans: InMemorySpanExporter) -> None:
    @opengrade.trace(name="answer")
    def answer(q: str) -> str:
        with opengrade.span("rerank", kind="reranker", input=q, attributes={"top_k": 5}) as s:
            assert s.is_recording and s.trace_id == opengrade.current_trace_id()
            s.set_output(["d1", "d2"])
        return "ok"

    answer("hi")
    got = _by_name(spans)
    rerank, root = got["rerank"], got["answer"]
    assert rerank.parent is not None and rerank.parent.span_id == root.context.span_id
    attrs = dict(rerank.attributes or {})
    assert attrs["openinference.span.kind"] == "RERANKER"
    assert attrs["input.value"] == "hi"
    assert attrs["output.value"] == '["d1", "d2"]'
    assert attrs["top_k"] == 5
    # The span's output does not leak to the enclosing traced call.
    assert dict(root.attributes or {})["output.value"] == "ok"


def test_span_records_error_and_reraises(spans: InMemorySpanExporter) -> None:
    with pytest.raises(ValueError, match="boom"):
        with opengrade.span("tool", kind="TOOL"):
            raise ValueError("boom")
    span = _by_name(spans)["tool"]
    assert span.status.status_code is StatusCode.ERROR
    assert [e.name for e in span.events] == ["exception"]


def test_span_async_with(spans: InMemorySpanExporter) -> None:
    async def main() -> None:
        async with opengrade.span("llm", kind="LLM") as s:
            s.set_attribute("llm.model_name", "m")
            await asyncio.sleep(0)

    asyncio.run(main())
    assert dict(_by_name(spans)["llm"].attributes or {})["llm.model_name"] == "m"


def test_span_not_reentrant(spans: InMemorySpanExporter) -> None:
    cm = opengrade.span("x")
    with cm:
        with pytest.raises(RuntimeError):
            cm.__enter__()


def test_unknown_kind_is_sent_as_is(spans: InMemorySpanExporter) -> None:
    with opengrade.span("x", kind="custom-step"):
        pass
    assert dict(_by_name(spans)["x"].attributes or {})["openinference.span.kind"] == "CUSTOM-STEP"


def test_set_user_session_tags_metadata(spans: InMemorySpanExporter) -> None:
    @opengrade.trace(name="answer")
    def answer() -> None:
        opengrade.set_user("u1")
        opengrade.set_session("chat-1")
        opengrade.set_tags("beta", "eu")
        opengrade.set_tags("eu", "rerank-v2")
        opengrade.set_metadata({"tenant": "acme"}, n=3, cfg={"k": 5}, _private="x")

    answer()
    attrs = dict(_by_name(spans)["answer"].attributes or {})
    assert attrs["user.id"] == "u1"
    assert attrs["session.id"] == "chat-1"
    assert list(attrs["tag.tags"]) == ["beta", "eu", "rerank-v2"]
    assert json.loads(str(attrs["metadata"])) == {"tenant": "acme", "n": 3, "cfg": '{"k": 5}'}


def test_setters_without_span_are_noops(spans: InMemorySpanExporter) -> None:
    opengrade.set_user("u1")
    opengrade.set_tags("x")
    opengrade.set_metadata(a=1)
    assert spans.get_finished_spans() == ()


def test_using_attributes_scopes_and_nests(spans: InMemorySpanExporter) -> None:
    with opengrade.using_attributes(user_id="u1", tags=["a"], metadata={"tenant": "acme"}):
        with opengrade.using_attributes(session_id="s1", tags=["b"], metadata={"tier": "gold"}):
            with opengrade.span("inner"):
                pass
        with opengrade.span("outer"):
            pass
    with opengrade.span("after"):
        pass

    got = _by_name(spans)
    inner = dict(got["inner"].attributes or {})
    assert inner["user.id"] == "u1" and inner["session.id"] == "s1"
    assert list(inner["tag.tags"]) == ["a", "b"]
    assert json.loads(str(inner["metadata"])) == {"tenant": "acme", "tier": "gold"}
    outer = dict(got["outer"].attributes or {})
    assert "session.id" not in outer and list(outer["tag.tags"]) == ["a"]
    assert "user.id" not in dict(got["after"].attributes or {})


def test_using_attributes_applies_to_trace_decorator(spans: InMemorySpanExporter) -> None:
    @opengrade.trace(name="answer")
    def answer() -> None:
        opengrade.set_tags("extra")

    with opengrade.using_attributes(user_id="u9", tags=["scoped"]):
        answer()
    attrs = dict(_by_name(spans)["answer"].attributes or {})
    assert attrs["user.id"] == "u9"
    assert list(attrs["tag.tags"]) == ["scoped", "extra"]


def test_models_and_dataclasses_are_captured_as_json() -> None:
    """A chat input (pydantic) must not show up in the UI as a Python repr."""
    import dataclasses
    import json

    from opengrade import chat_input
    from opengrade._trace import truncate_value

    @dataclasses.dataclass
    class Query:
        text: str
        top_k: int = 3

    chat = chat_input({"history": [{"role": "user", "content": "hi"}], "question": "and now?"})
    assert json.loads(truncate_value(chat)) == {
        "history": [{"role": "user", "content": "hi"}],
        "question": "and now?",
    }
    assert json.loads(truncate_value({"q": Query("x")})) == {"q": {"text": "x", "top_k": 3}}
