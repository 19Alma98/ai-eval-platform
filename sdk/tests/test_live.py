from __future__ import annotations

import asyncio
from collections.abc import Iterator

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import aiobs
from aiobs import _live, _otel
from aiobs._run_context import ACTIVE_RUN

_shared_exporter: InMemorySpanExporter | None = None


@pytest.fixture(scope="module", autouse=True)
def _reset_otel() -> Iterator[None]:
    global _shared_exporter
    _otel._reset_for_tests()
    _shared_exporter = None
    yield
    _shared_exporter = None
    _otel._reset_for_tests()


@pytest.fixture(autouse=True)
def _reset_live(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv("AIOBS_LIVE", raising=False)
    monkeypatch.delenv("AIOBS_LIVE_SAMPLE_RATE", raising=False)
    _live._reset_for_tests()
    yield
    _live._reset_for_tests()


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


def _by_name(exporter: InMemorySpanExporter) -> dict[str, dict[str, object]]:
    return {s.name: dict(s.attributes or {}) for s in exporter.get_finished_spans()}


def test_live_off_by_default(spans: InMemorySpanExporter) -> None:
    @aiobs.trace(name="answer")
    def answer(q: str) -> str:
        return "a"

    answer("q")
    assert _live.LIVE_ATTR not in _by_name(spans)["answer"]


def test_live_marks_only_outermost_span(spans: InMemorySpanExporter) -> None:
    _live.configure(enabled=True, sample_rate=1.0)

    @aiobs.trace(name="retrieve")
    def retrieve(q: str) -> str:
        return "ctx"

    @aiobs.trace(name="answer")
    def answer(q: str) -> str:
        return retrieve(q) + "!"

    answer("q")
    attrs = _by_name(spans)
    assert attrs["answer"][_live.LIVE_ATTR] is True
    assert attrs["answer"][_live.LIVE_JUDGE_ATTR] is True
    assert attrs["answer"][_live.LIVE_SAMPLE_RATE_ATTR] == 1.0
    assert _live.LIVE_ATTR not in attrs["retrieve"]


def test_live_sample_rate_zero_records_without_judge(spans: InMemorySpanExporter) -> None:
    _live.configure(enabled=True, sample_rate=0.0)

    @aiobs.trace(name="answer")
    def answer(q: str) -> str:
        return "a"

    answer("q")
    attrs = _by_name(spans)["answer"]
    assert attrs[_live.LIVE_ATTR] is True
    assert attrs[_live.LIVE_JUDGE_ATTR] is False


def test_live_env_vars(spans: InMemorySpanExporter, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIOBS_LIVE", "1")
    monkeypatch.setenv("AIOBS_LIVE_SAMPLE_RATE", "0")

    @aiobs.trace(name="answer")
    def answer(q: str) -> str:
        return "a"

    answer("q")
    attrs = _by_name(spans)["answer"]
    assert attrs[_live.LIVE_ATTR] is True
    assert attrs[_live.LIVE_JUDGE_ATTR] is False


def test_decorator_live_flag_overrides_global(spans: InMemorySpanExporter) -> None:
    @aiobs.trace(name="forced", live=True)
    def forced() -> str:
        return "a"

    forced()
    assert _by_name(spans)["forced"][_live.LIVE_ATTR] is True

    _live.configure(enabled=True)
    spans.clear()

    @aiobs.trace(name="excluded", live=False)
    def excluded() -> str:
        return "a"

    excluded()
    assert _live.LIVE_ATTR not in _by_name(spans)["excluded"]


def test_live_skipped_inside_experiment_run(spans: InMemorySpanExporter) -> None:
    _live.configure(enabled=True)

    class _Recorder:
        def _capture_output(self, value: object) -> None: ...

        def _capture_documents(self, documents: list[dict[str, object]]) -> None: ...

    @aiobs.trace(name="answer")
    def answer() -> str:
        return "a"

    token = ACTIVE_RUN.set(_Recorder())
    try:
        answer()
    finally:
        ACTIVE_RUN.reset(token)
    assert _live.LIVE_ATTR not in _by_name(spans)["answer"]


def test_live_context_released_after_error(spans: InMemorySpanExporter) -> None:
    _live.configure(enabled=True)

    @aiobs.trace(name="boom")
    def boom() -> None:
        raise RuntimeError("x")

    @aiobs.trace(name="after")
    def after() -> str:
        return "a"

    with pytest.raises(RuntimeError):
        boom()
    after()
    attrs = _by_name(spans)
    assert attrs["boom"][_live.LIVE_ATTR] is True
    assert attrs["after"][_live.LIVE_ATTR] is True


def test_live_async(spans: InMemorySpanExporter) -> None:
    _live.configure(enabled=True)

    @aiobs.trace_async(name="inner")
    async def inner() -> str:
        return "x"

    @aiobs.trace_async(name="outer")
    async def outer() -> str:
        return await inner()

    asyncio.run(outer())
    attrs = _by_name(spans)
    assert attrs["outer"][_live.LIVE_ATTR] is True
    assert _live.LIVE_ATTR not in attrs["inner"]


def test_should_judge_is_deterministic_and_proportional() -> None:
    ids = [(i * 0x9E3779B97F4A7C15) & ((1 << 128) - 1) for i in range(1, 20001)]
    picked = sum(_live.should_judge(t, 0.25) for t in ids)
    assert 0.22 < picked / len(ids) < 0.28
    assert all(_live.should_judge(t, 0.25) == _live.should_judge(t, 0.25) for t in ids[:100])
    assert not any(_live.should_judge(t, 0.0) for t in ids[:100])
    assert all(_live.should_judge(t, 1.0) for t in ids[:100])


def test_configure_rejects_out_of_range_rate() -> None:
    with pytest.raises(ValueError):
        _live.configure(enabled=True, sample_rate=1.5)


def test_init_with_bad_rate_disables_live_without_raising() -> None:
    aiobs.init(project_id="p", live=True, live_sample_rate=2.0, instrument=False, force=True)
    try:
        assert _live.is_enabled() is False
    finally:
        _otel._reset_for_tests()
