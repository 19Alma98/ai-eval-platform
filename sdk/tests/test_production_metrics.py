from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Iterator
from typing import Any

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import aiobs
from aiobs import _config, _otel, _production, _scores
from aiobs._run_context import ACTIVE_RUN

_exporter = InMemorySpanExporter()


class Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[dict[str, Any]]]] = []
        self.lock = threading.Lock()

    def __call__(self, project_id: str, scores: list[dict[str, Any]]) -> None:
        with self.lock:
            self.calls.append((project_id, list(scores)))

    @property
    def scores(self) -> list[dict[str, Any]]:
        return [s for _, batch in self.calls for s in batch]


@pytest.fixture(scope="module", autouse=True)
def _tracer() -> Iterator[None]:
    _otel._reset_for_tests()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(_exporter))
    trace.set_tracer_provider(provider)
    yield
    _otel._reset_for_tests()


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> Iterator[Recorder]:
    monkeypatch.setattr(_config, "_ACTIVE_PROJECT_ID", None)
    monkeypatch.setenv("AIOBS_PROJECT_ID", "p1")
    _exporter.clear()
    _production._reset_for_tests()
    recorder = Recorder()
    _scores._reset_for_tests(recorder, interval=60.0)
    yield recorder
    _production._reset_for_tests()
    _scores._reset_for_tests()


def _span_trace_id(name: str) -> str:
    (span,) = [s for s in _exporter.get_finished_spans() if s.name == name]
    return format(span.context.trace_id, "032x")


def test_traced_call_runs_metrics_with_captured_input_and_documents(sent: Recorder) -> None:
    seen: list[aiobs.Sample] = []

    @aiobs.metric(threshold=0.5, requires=("documents",))
    def cites(s: aiobs.Sample) -> float:
        seen.append(s)
        return 1.0

    @aiobs.trace(name="retrieve")
    def retrieve(q: str) -> list[dict[str, Any]]:
        docs = [{"id": "d1", "text": "doc"}]
        aiobs.set_retrieval_documents(docs)
        return docs

    @aiobs.trace(name="answer", metrics=[cites])
    def answer(q: str) -> str:
        retrieve(q)
        return f"answer to {q}"

    assert answer("hi") == "answer to hi"
    assert aiobs.flush()

    (sample,) = seen
    assert sample.input == "hi" and sample.output == "answer to hi"
    assert sample.documents == [{"id": "d1", "text": "doc"}]
    assert sample.expected is None
    assert sent.scores == [
        {
            "trace_id": _span_trace_id("answer"),
            "name": "cites",
            "value": 1.0,
            "source": "sdk",
            "threshold": 0.5,
        }
    ]
    assert sample.trace_id == _span_trace_id("answer")


def test_set_input_overrides_call_arguments(sent: Recorder) -> None:
    seen: list[Any] = []

    @aiobs.metric
    def record(s: aiobs.Sample) -> float:
        seen.append(s.input)
        return 1.0

    @aiobs.trace(name="handler", metrics=[record])
    def handler(request: dict[str, Any], user: str) -> str:
        aiobs.set_input(request["question"])
        return "ok"

    handler({"question": "q?"}, "u1")
    aiobs.flush()
    assert seen == ["q?"]


def test_input_falls_back_to_args_and_kwargs(sent: Recorder) -> None:
    seen: list[Any] = []

    @aiobs.metric
    def record(s: aiobs.Sample) -> float:
        seen.append(s.input)
        return 1.0

    @aiobs.trace(name="two_args", metrics=[record])
    def two_args(a: str, b: str) -> str:
        return "ok"

    @aiobs.trace(name="one_kwarg", metrics=[record])
    def one_kwarg(*, question: str) -> str:
        return "ok"

    two_args("x", b="y")
    one_kwarg(question="q")
    aiobs.flush()
    # Two calls run on a 2-thread pool: order is not guaranteed.
    assert sorted(seen, key=repr) == sorted([{"args": ["x"], "kwargs": {"b": "y"}}, "q"], key=repr)


def test_async_traced_call_runs_metrics(sent: Recorder) -> None:
    @aiobs.metric
    def length(s: aiobs.Sample) -> float:
        return float(len(s.output))

    @aiobs.trace_async(name="async_answer", metrics=[length])
    async def async_answer(q: str) -> str:
        await asyncio.sleep(0)
        return "abcd"

    assert asyncio.run(async_answer("q")) == "abcd"
    aiobs.flush()
    assert [s["value"] for s in sent.scores] == [4.0]


def test_zero_sample_rate_skips(sent: Recorder) -> None:
    @aiobs.trace(
        name="never", metrics=[aiobs.metric(lambda s: 1.0, name="m")], metrics_sample_rate=0.0
    )
    def never(q: str) -> str:
        return "ok"

    never("q")
    aiobs.flush()
    assert sent.scores == []


def test_skipped_inside_experiment_run(sent: Recorder) -> None:
    @aiobs.trace(name="in_run", metrics=[aiobs.metric(lambda s: 1.0, name="m")])
    def in_run(q: str) -> str:
        return "ok"

    token = ACTIVE_RUN.set(object())  # type: ignore[arg-type]
    try:
        in_run("q")
    finally:
        ACTIVE_RUN.reset(token)
    aiobs.flush()
    assert sent.scores == []


def test_raising_function_is_not_scored(sent: Recorder) -> None:
    @aiobs.trace(name="boom", metrics=[aiobs.metric(lambda s: 1.0, name="m")])
    def boom(q: str) -> str:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        boom("q")
    aiobs.flush()
    assert sent.scores == []


def test_broken_metric_and_missing_requirement_store_nothing(sent: Recorder) -> None:
    @aiobs.metric
    def broken(s: aiobs.Sample) -> float:
        raise ValueError("bad metric")

    @aiobs.metric(requires=("expected",))
    def needs_gold(s: aiobs.Sample) -> float:
        return 1.0

    @aiobs.metric
    def fine(s: aiobs.Sample) -> float:
        return 0.5

    @aiobs.trace(name="mixed", metrics=[broken, needs_gold, fine])
    def mixed(q: str) -> str:
        return "ok"

    assert mixed("q") == "ok"
    aiobs.flush()
    assert [s["name"] for s in sent.scores] == ["fine"]


def test_invalid_metric_configuration_fails_at_decoration() -> None:
    with pytest.raises(ValueError, match="name"):
        aiobs.trace(metrics=[lambda s: 1.0])
    with pytest.raises(ValueError, match="duplicate"):
        aiobs.trace(
            metrics=[aiobs.metric(lambda s: 1.0, name="m"), aiobs.metric(lambda s: 0.0, name="m")]
        )
    with pytest.raises(ValueError, match="sample_rate"):
        aiobs.trace(metrics=[aiobs.metric(lambda s: 1.0, name="m")], metrics_sample_rate=1.5)
    with pytest.raises(ValueError, match="sample_rate"):
        aiobs.trace_async(
            metrics=[aiobs.metric(lambda s: 1.0, name="m")], metrics_sample_rate=float("nan")
        )


@pytest.mark.parametrize("bad", [True, False, "0.5", None])
def test_sample_rate_must_be_a_real_number(bad: Any) -> None:
    with pytest.raises(ValueError, match=r"metrics_sample_rate must be a number within \[0, 1\]"):
        aiobs.trace(metrics=[aiobs.metric(lambda s: 1.0, name="m")], metrics_sample_rate=bad)


def test_sync_trace_with_metrics_rejects_coroutine_and_generator_functions() -> None:
    decorate = aiobs.trace(metrics=[aiobs.metric(lambda s: 1.0, name="m")])

    async def coro() -> str:
        return "x"

    def gen() -> Iterator[str]:
        yield "x"

    async def agen() -> Any:
        yield "x"

    for fn in (coro, gen, agen):
        with pytest.raises(TypeError, match="trace_async|regular function"):
            decorate(fn)  # type: ignore[arg-type]


def test_trace_async_with_metrics_rejects_non_coroutine_functions() -> None:
    decorate = aiobs.trace_async(metrics=[aiobs.metric(lambda s: 1.0, name="m")])

    def plain() -> str:
        return "x"

    async def agen() -> Any:
        yield "x"

    for fn in (plain, agen):
        with pytest.raises(TypeError, match="coroutine function"):
            decorate(fn)


def test_without_metrics_decorators_accept_any_callable() -> None:
    def gen() -> Iterator[str]:
        yield "x"

    aiobs.trace(name="g")(gen)  # unchanged behaviour when metrics are not used


# --- isolation from traced code -----------------------------------------------------


def test_metric_calling_traced_code_creates_no_spans_or_scores(sent: Recorder) -> None:
    from opentelemetry import context as otel_context

    inner_calls: list[str] = []
    suppressed: list[Any] = []

    @aiobs.metric
    def inner_metric(s: aiobs.Sample) -> float:
        inner_calls.append("inner")
        return 1.0

    @aiobs.trace(name="judge_helper", metrics=[inner_metric], live=True)
    def judge_helper(text: str) -> str:
        return text.upper()

    @aiobs.trace_async(name="async_judge_helper", metrics=[inner_metric], live=True)
    async def async_judge_helper(text: str) -> str:
        return text.lower()

    @aiobs.metric
    def judge(s: aiobs.Sample) -> float:
        suppressed.append(otel_context.get_value(_production._SUPPRESS_KEY))
        assert judge_helper(str(s.output)) == "OK"
        return 1.0

    @aiobs.metric
    async def async_judge(s: aiobs.Sample) -> float:
        suppressed.append(otel_context.get_value(_production._SUPPRESS_KEY))
        assert await async_judge_helper(str(s.output)) == "ok"
        return 0.5

    @aiobs.trace(name="outer", metrics=[judge, async_judge])
    def outer(q: str) -> str:
        return "ok"

    outer("q")
    assert aiobs.flush()
    assert [s.name for s in _exporter.get_finished_spans()] == ["outer"]
    assert sorted(s["name"] for s in sent.scores) == ["async_judge", "judge"]
    assert inner_calls == []
    assert suppressed == [True, True]


def test_nested_set_input_does_not_overwrite_outer_input(sent: Recorder) -> None:
    seen: list[aiobs.Sample] = []

    @aiobs.metric
    def record(s: aiobs.Sample) -> float:
        seen.append(s)
        return 1.0

    @aiobs.trace(name="rewrite")
    def rewrite(q: str) -> str:
        aiobs.set_input("rewritten")
        aiobs.set_retrieval_documents([{"id": "d1"}])
        return q

    @aiobs.trace(name="outer_input", metrics=[record])
    def outer_input(q: str) -> str:
        return rewrite(q)

    outer_input("original")
    assert aiobs.flush()
    (sample,) = seen
    assert sample.input == "original"
    assert sample.documents == [{"id": "d1"}]  # documents still bubble up


def test_async_metric_runs_on_worker(sent: Recorder) -> None:
    threads: list[str] = []

    @aiobs.metric
    async def async_len(s: aiobs.Sample) -> float:
        await asyncio.sleep(0)
        threads.append(threading.current_thread().name)
        return float(len(s.output))

    @aiobs.trace(name="with_async_metric", metrics=[async_len])
    def with_async_metric(q: str) -> str:
        return "abc"

    with_async_metric("q")
    assert aiobs.flush()
    assert [s["value"] for s in sent.scores] == [3.0]
    assert threads and threads[0] != threading.current_thread().name


def test_hung_async_metric_times_out_as_failure(
    sent: Recorder, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_production, "METRIC_TIMEOUT_S", 0.05)
    never = threading.Event()

    @aiobs.metric
    async def hung(s: aiobs.Sample) -> float:
        await asyncio.get_running_loop().run_in_executor(None, never.wait, 5)
        return 1.0

    @aiobs.metric
    def after(s: aiobs.Sample) -> float:
        return 1.0

    @aiobs.trace(name="hangs", metrics=[hung, after])
    def hangs(q: str) -> str:
        return q

    caplog.set_level(logging.DEBUG, logger="aiobs")
    hangs("a")
    hangs("b")
    assert aiobs.flush()
    never.set()
    assert len(_warnings(caplog, "production metric 'hung' timed out")) == 1
    assert [s["name"] for s in sent.scores] == ["after", "after"]


def test_fractional_sample_rate_is_deterministic_per_trace(
    sent: Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    from opentelemetry.sdk.trace.id_generator import IdGenerator

    half = 1 << 63  # rate 0.5 samples low-64-bit trace ids below 2**63
    ids = iter([(1 << 64) | 1, (1 << 64) | half, (2 << 64) | 2, (2 << 64) | (half + 5)])

    class Ids(IdGenerator):
        def generate_span_id(self) -> int:
            return 1

        def generate_trace_id(self) -> int:
            return next(ids)

    tracer = trace.get_tracer("aiobs")  # the provider caches it: the one @aiobs.trace uses
    monkeypatch.setattr(tracer, "id_generator", Ids())

    @aiobs.trace(
        name="sampled", metrics=[aiobs.metric(lambda s: 1.0, name="m")], metrics_sample_rate=0.5
    )
    def sampled(q: str) -> str:
        return q

    for i in range(4):
        sampled(str(i))
    assert aiobs.flush()
    assert sorted(s["trace_id"] for s in sent.scores) == [
        format((1 << 64) | 1, "032x"),
        format((2 << 64) | 2, "032x"),
    ]


def test_exit_handlers_share_one_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = _Clock()
    calls: list[tuple[str, float]] = []

    def drain(timeout: float) -> bool:
        calls.append(("metrics", timeout))
        clock.now += 2.0
        return True

    def scores_flush(timeout: float) -> bool:
        calls.append(("scores", timeout))
        clock.now += 1.0
        return True

    monkeypatch.setattr(_scores, "time", clock)
    monkeypatch.setattr(_production, "time", clock)
    monkeypatch.setattr(_scores, "_EXIT_DEADLINE", None)
    monkeypatch.setattr(_production, "drain", drain)
    monkeypatch.setattr(_scores, "flush", scores_flush)

    _production._at_exit()
    _scores._at_exit()
    total = _scores.EXIT_FLUSH_TIMEOUT_S
    assert calls == [("metrics", total), ("scores", total - 2.0), ("scores", total - 3.0)]


# --- never raise / never block the caller -------------------------------------------


def _warnings(caplog: pytest.LogCaptureFixture, needle: str) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.levelno == logging.WARNING and needle in r.getMessage()]


def test_full_queue_drops_with_one_warning_and_never_blocks(
    sent: Recorder, caplog: pytest.LogCaptureFixture
) -> None:
    _production._reset_for_tests(workers=1, max_queue=1)
    started = threading.Event()
    release = threading.Event()

    @aiobs.metric
    def slow(s: aiobs.Sample) -> float:
        started.set()
        assert release.wait(10)
        return 1.0

    @aiobs.trace(name="busy", metrics=[slow])
    def busy(q: str) -> str:
        return q

    caplog.set_level(logging.DEBUG, logger="aiobs")
    assert busy("1") == "1"  # taken by the only worker, which then blocks
    assert started.wait(10)
    assert busy("2") == "2"  # fills the queue
    assert busy("3") == "3"  # dropped: caller is not blocked
    assert busy("4") == "4"  # dropped again: no second warning
    assert len(_warnings(caplog, "production metrics queue full")) == 1
    assert _production.dropped() == 2

    release.set()
    assert aiobs.flush()
    assert len(sent.scores) == 2


def test_metric_failures_are_rate_limited(sent: Recorder, caplog: pytest.LogCaptureFixture) -> None:
    @aiobs.metric
    def broken(s: aiobs.Sample) -> float:
        raise ValueError("bad metric")

    @aiobs.trace(name="often", metrics=[broken])
    def often(q: str) -> str:
        return q

    caplog.set_level(logging.DEBUG, logger="aiobs")
    for i in range(3):
        often(str(i))
    assert aiobs.flush()
    assert len(_warnings(caplog, "production metric 'broken' failed")) == 1
    assert sent.scores == []


def test_unexpected_worker_error_is_logged_and_worker_survives(
    sent: Recorder, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = _production.missing_requirement
    calls = {"n": 0}

    def flaky(sample: aiobs.Sample, requires: Any) -> str | None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("internal bug")
        return real(sample, requires)

    monkeypatch.setattr(_production, "missing_requirement", flaky)
    _production._reset_for_tests(workers=1)

    @aiobs.trace(name="job", metrics=[aiobs.metric(lambda s: 1.0, name="m")])
    def job(q: str) -> str:
        return q

    caplog.set_level(logging.DEBUG, logger="aiobs")
    job("a")
    job("b")
    assert aiobs.flush()
    assert len(_warnings(caplog, "internal bug")) == 1
    assert [s["name"] for s in sent.scores] == ["m"]


def test_scheduling_failure_never_reaches_the_caller(
    sent: Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(*args: Any, **kwargs: Any) -> bool:
        raise RuntimeError("cannot start thread")

    monkeypatch.setattr(_production, "_submit", explode)

    @aiobs.trace(name="safe", metrics=[aiobs.metric(lambda s: 1.0, name="m")])
    def safe(q: str) -> str:
        return q

    assert safe("x") == "x"
    assert aiobs.flush()
    assert sent.scores == []


def test_missing_project_warns_once_and_skips(
    sent: Recorder, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AIOBS_PROJECT_ID")

    @aiobs.trace(name="noproj", metrics=[aiobs.metric(lambda s: 1.0, name="m")])
    def noproj(q: str) -> str:
        return q

    caplog.set_level(logging.DEBUG, logger="aiobs")
    assert noproj("a") == "a"
    assert noproj("b") == "b"
    assert aiobs.flush()
    assert len(_warnings(caplog, "production metrics skipped")) == 1
    assert sent.scores == []


def test_after_fork_in_child_resets_pool(sent: Recorder) -> None:
    @aiobs.trace(name="pre_fork", metrics=[aiobs.metric(lambda s: 1.0, name="m")])
    def pre_fork(q: str) -> str:
        return q

    pre_fork("a")
    assert aiobs.flush()
    assert _production._POOL is not None
    old_lock = _production._LOCK
    _production._after_fork_in_child()
    assert _production._POOL is None
    assert _production._LOCK is not old_lock
    pre_fork("b")  # a fresh pool is built lazily
    assert aiobs.flush()
    assert len(sent.scores) == 2


# --- flush budget ----------------------------------------------------------------------


class _Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def monotonic(self) -> float:
        return self.now


def test_flush_shares_one_deadline_spans_then_metrics_then_scores(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _Clock()
    calls: list[tuple[str, float]] = []

    class Provider:
        def force_flush(self, timeout_millis: int) -> bool:
            calls.append(("spans", timeout_millis / 1000))
            clock.now += 1.0
            return True

    def drain(timeout: float) -> bool:
        calls.append(("metrics", timeout))
        clock.now += 1.5
        return True

    def scores_flush(timeout: float) -> bool:
        calls.append(("scores", timeout))
        return True

    monkeypatch.setattr(_otel, "time", clock)
    monkeypatch.setattr(_otel, "_PROVIDER", Provider())
    monkeypatch.setattr(_production, "drain", drain)
    monkeypatch.setattr(_scores, "flush", scores_flush)

    assert _otel.flush(5000)
    assert calls == [("spans", 5.0), ("metrics", 4.0), ("scores", 2.5)]


def test_flush_survives_a_raising_drain(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def drain(timeout: float) -> bool:
        raise RuntimeError("boom")

    def scores_flush(timeout: float) -> bool:
        calls.append("scores")
        return True

    monkeypatch.setattr(_otel, "_PROVIDER", None)
    monkeypatch.setattr(_production, "drain", drain)
    monkeypatch.setattr(_scores, "flush", scores_flush)

    assert _otel.flush(1000) is False
    assert calls == ["scores"]


def test_flush_budget_is_never_negative(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = _Clock()
    calls: list[tuple[str, float]] = []

    def drain(timeout: float) -> bool:
        calls.append(("metrics", timeout))
        clock.now += 10.0
        return False

    def scores_flush(timeout: float) -> bool:
        calls.append(("scores", timeout))
        return True

    monkeypatch.setattr(_otel, "time", clock)
    monkeypatch.setattr(_otel, "_PROVIDER", None)
    monkeypatch.setattr(_production, "drain", drain)
    monkeypatch.setattr(_scores, "flush", scores_flush)

    assert _otel.flush(1000) is False
    assert calls == [("metrics", 1.0), ("scores", 0.0)]
