from __future__ import annotations

import asyncio
import functools
import inspect
import logging
import threading
from collections.abc import Iterator
from typing import Any

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import opengrade
from opengrade import _config, _otel, _production, _scores
from opengrade._run_context import ACTIVE_RUN

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
    monkeypatch.setenv("OPENGRADE_PROJECT_ID", "p1")
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
    seen: list[opengrade.Sample] = []

    @opengrade.metric(threshold=0.5, requires=("documents",))
    def cites(s: opengrade.Sample) -> float:
        seen.append(s)
        return 1.0

    @opengrade.trace(name="retrieve")
    def retrieve(q: str) -> list[dict[str, Any]]:
        docs = [{"id": "d1", "text": "doc"}]
        opengrade.set_retrieval_documents(docs)
        return docs

    @opengrade.trace(name="answer", metrics=[cites])
    def answer(q: str) -> str:
        retrieve(q)
        return f"answer to {q}"

    assert answer("hi") == "answer to hi"
    assert opengrade.flush()

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

    @opengrade.metric
    def record(s: opengrade.Sample) -> float:
        seen.append(s.input)
        return 1.0

    @opengrade.trace(name="handler", metrics=[record])
    def handler(request: dict[str, Any], user: str) -> str:
        opengrade.set_input(request["question"])
        return "ok"

    handler({"question": "q?"}, "u1")
    opengrade.flush()
    assert seen == ["q?"]


def test_metric_sees_snapshot_not_later_mutations(sent: Recorder) -> None:
    """Queued jobs must not observe mutations after the traced call returns."""
    release = threading.Event()
    seen: list[tuple[Any, Any, list[dict[str, Any]]]] = []

    @opengrade.metric
    def record(s: opengrade.Sample) -> float:
        assert release.wait(timeout=2.0)
        seen.append((s.input, s.output, s.documents))
        return 1.0

    docs = [{"id": "d1", "meta": {"n": 1}}]
    request = {"q": "hi"}

    @opengrade.trace(name="handler", metrics=[record])
    def handler(req: dict[str, Any]) -> dict[str, Any]:
        opengrade.set_retrieval_documents(docs)
        return {"text": "ok"}

    out = handler(request)
    request["q"] = "mutated-input"
    docs[0]["meta"]["n"] = 99
    out["text"] = "mutated-output"
    release.set()
    assert opengrade.flush()

    (sample_input, sample_output, sample_docs) = seen[0]
    assert sample_input == {"q": "hi"}
    assert sample_output == {"text": "ok"}
    assert sample_docs == [{"id": "d1", "meta": {"n": 1}}]


def test_oversized_sample_skips_metrics(
    sent: Recorder, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(_production, "MAX_METRIC_SAMPLE_BYTES", 64)

    @opengrade.metric
    def record(s: opengrade.Sample) -> float:
        return 1.0

    @opengrade.trace(name="big", metrics=[record])
    def big(q: str) -> str:
        return "x" * 200

    with caplog.at_level(logging.WARNING, logger="opengrade"):
        assert big("q") == "x" * 200
        assert opengrade.flush()

    assert sent.scores == []
    assert any("sample is" in r.message and "limit 64" in r.message for r in caplog.records)


def test_uncopyable_sample_skips_metrics(sent: Recorder, caplog: pytest.LogCaptureFixture) -> None:
    class Bad:
        def __deepcopy__(self, memo: dict[int, Any]) -> Any:
            raise RuntimeError("no deepcopy")

        def __str__(self) -> str:
            raise RuntimeError("no str")

    @opengrade.metric
    def record(s: opengrade.Sample) -> float:
        return 1.0

    @opengrade.trace(name="bad", metrics=[record])
    def bad(_q: str) -> Bad:
        return Bad()

    with caplog.at_level(logging.WARNING, logger="opengrade"):
        assert isinstance(bad("q"), Bad)
        assert opengrade.flush()

    assert sent.scores == []
    assert any("could not snapshot" in r.message for r in caplog.records)


def test_input_falls_back_to_args_and_kwargs(sent: Recorder) -> None:
    seen: list[Any] = []

    @opengrade.metric
    def record(s: opengrade.Sample) -> float:
        seen.append(s.input)
        return 1.0

    @opengrade.trace(name="two_args", metrics=[record])
    def two_args(a: str, b: str) -> str:
        return "ok"

    @opengrade.trace(name="one_kwarg", metrics=[record])
    def one_kwarg(*, question: str) -> str:
        return "ok"

    two_args("x", b="y")
    one_kwarg(question="q")
    opengrade.flush()
    # Two calls run on a 2-thread pool: order is not guaranteed.
    assert sorted(seen, key=repr) == sorted([{"args": ["x"], "kwargs": {"b": "y"}}, "q"], key=repr)


def test_async_traced_call_runs_metrics(sent: Recorder) -> None:
    @opengrade.metric
    def length(s: opengrade.Sample) -> float:
        return float(len(s.output))

    @opengrade.trace_async(name="async_answer", metrics=[length])
    async def async_answer(q: str) -> str:
        await asyncio.sleep(0)
        return "abcd"

    assert asyncio.run(async_answer("q")) == "abcd"
    opengrade.flush()
    assert [s["value"] for s in sent.scores] == [4.0]


def test_zero_sample_rate_skips(sent: Recorder) -> None:
    @opengrade.trace(
        name="never", metrics=[opengrade.metric(lambda s: 1.0, name="m")], metrics_sample_rate=0.0
    )
    def never(q: str) -> str:
        return "ok"

    never("q")
    opengrade.flush()
    assert sent.scores == []


def test_skipped_inside_experiment_run(sent: Recorder) -> None:
    @opengrade.trace(name="in_run", metrics=[opengrade.metric(lambda s: 1.0, name="m")])
    def in_run(q: str) -> str:
        return "ok"

    token = ACTIVE_RUN.set(object())  # type: ignore[arg-type]
    try:
        in_run("q")
    finally:
        ACTIVE_RUN.reset(token)
    opengrade.flush()
    assert sent.scores == []


def test_raising_function_is_not_scored(sent: Recorder) -> None:
    @opengrade.trace(name="boom", metrics=[opengrade.metric(lambda s: 1.0, name="m")])
    def boom(q: str) -> str:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        boom("q")
    opengrade.flush()
    assert sent.scores == []


def test_broken_metric_and_missing_requirement_store_error_and_success(sent: Recorder) -> None:
    @opengrade.metric
    def broken(s: opengrade.Sample) -> float:
        raise ValueError("bad metric")

    @opengrade.metric(requires=("expected",))
    def needs_gold(s: opengrade.Sample) -> float:
        return 1.0

    @opengrade.metric
    def fine(s: opengrade.Sample) -> float:
        return 0.5

    @opengrade.trace(name="mixed", metrics=[broken, needs_gold, fine])
    def mixed(q: str) -> str:
        return "ok"

    assert mixed("q") == "ok"
    opengrade.flush()
    by_name = {s["name"]: s for s in sent.scores}
    assert set(by_name) == {"broken", "fine"}
    assert by_name["broken"]["label"] == "ERROR"
    assert by_name["broken"]["value"] is None
    assert "ValueError" in by_name["broken"]["explanation"]
    assert "bad metric" in by_name["broken"]["explanation"]
    assert by_name["fine"]["value"] == 0.5


def test_invalid_metric_configuration_fails_at_decoration() -> None:
    with pytest.raises(ValueError, match="name"):
        opengrade.trace(metrics=[lambda s: 1.0])
    with pytest.raises(ValueError, match="duplicate"):
        opengrade.trace(
            metrics=[opengrade.metric(lambda s: 1.0, name="m"), opengrade.metric(lambda s: 0.0, name="m")]
        )
    with pytest.raises(ValueError, match="sample_rate"):
        opengrade.trace(metrics=[opengrade.metric(lambda s: 1.0, name="m")], metrics_sample_rate=1.5)
    with pytest.raises(ValueError, match="sample_rate"):
        opengrade.trace_async(
            metrics=[opengrade.metric(lambda s: 1.0, name="m")], metrics_sample_rate=float("nan")
        )


@pytest.mark.parametrize("bad", [True, False, "0.5", None])
def test_sample_rate_must_be_a_real_number(bad: Any) -> None:
    with pytest.raises(ValueError, match=r"metrics_sample_rate must be a number within \[0, 1\]"):
        opengrade.trace(metrics=[opengrade.metric(lambda s: 1.0, name="m")], metrics_sample_rate=bad)


def test_sync_trace_with_metrics_rejects_coroutine_and_generator_functions() -> None:
    decorate = opengrade.trace(metrics=[opengrade.metric(lambda s: 1.0, name="m")])

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
    decorate = opengrade.trace_async(metrics=[opengrade.metric(lambda s: 1.0, name="m")])

    def plain() -> str:
        return "x"

    async def agen() -> Any:
        yield "x"

    for fn in (plain, agen):
        with pytest.raises(TypeError, match="markcoroutinefunction"):
            decorate(fn)


def test_trace_async_with_metrics_accepts_partial_and_marked_callables() -> None:
    decorate = opengrade.trace_async(metrics=[opengrade.metric(lambda s: 1.0, name="m")])

    async def coro(prefix: str, q: str) -> str:
        return f"{prefix}{q}"

    decorate(functools.partial(coro, "p:"))
    decorate(functools.partial(functools.partial(coro, "a:"), "b:"))

    def looks_sync(q: str) -> str:
        return q

    inspect.markcoroutinefunction(looks_sync)
    decorate(looks_sync)


def test_sync_trace_with_metrics_rejects_partial_of_coroutine() -> None:
    decorate = opengrade.trace(metrics=[opengrade.metric(lambda s: 1.0, name="m")])

    async def coro(prefix: str, q: str) -> str:
        return f"{prefix}{q}"

    with pytest.raises(TypeError, match="trace_async|regular function"):
        decorate(functools.partial(coro, "p:"))  # type: ignore[arg-type]


def test_without_metrics_decorators_accept_any_callable() -> None:
    def gen() -> Iterator[str]:
        yield "x"

    opengrade.trace(name="g")(gen)  # unchanged behaviour when metrics are not used


# --- isolation from traced code -----------------------------------------------------


def test_metric_calling_traced_code_creates_no_spans_or_scores(sent: Recorder) -> None:
    from opentelemetry import context as otel_context

    inner_calls: list[str] = []
    suppressed: list[Any] = []

    @opengrade.metric
    def inner_metric(s: opengrade.Sample) -> float:
        inner_calls.append("inner")
        return 1.0

    @opengrade.trace(name="judge_helper", metrics=[inner_metric], live=True)
    def judge_helper(text: str) -> str:
        return text.upper()

    @opengrade.trace_async(name="async_judge_helper", metrics=[inner_metric], live=True)
    async def async_judge_helper(text: str) -> str:
        return text.lower()

    @opengrade.metric
    def judge(s: opengrade.Sample) -> float:
        suppressed.append(otel_context.get_value(_production._SUPPRESS_KEY))
        assert judge_helper(str(s.output)) == "OK"
        return 1.0

    @opengrade.metric
    async def async_judge(s: opengrade.Sample) -> float:
        suppressed.append(otel_context.get_value(_production._SUPPRESS_KEY))
        assert await async_judge_helper(str(s.output)) == "ok"
        return 0.5

    @opengrade.trace(name="outer", metrics=[judge, async_judge])
    def outer(q: str) -> str:
        return "ok"

    outer("q")
    assert opengrade.flush()
    assert [s.name for s in _exporter.get_finished_spans()] == ["outer"]
    assert sorted(s["name"] for s in sent.scores) == ["async_judge", "judge"]
    assert inner_calls == []
    assert suppressed == [True, True]


def test_nested_set_input_does_not_overwrite_outer_input(sent: Recorder) -> None:
    seen: list[opengrade.Sample] = []

    @opengrade.metric
    def record(s: opengrade.Sample) -> float:
        seen.append(s)
        return 1.0

    @opengrade.trace(name="rewrite")
    def rewrite(q: str) -> str:
        opengrade.set_input("rewritten")
        opengrade.set_retrieval_documents([{"id": "d1"}])
        return q

    @opengrade.trace(name="outer_input", metrics=[record])
    def outer_input(q: str) -> str:
        return rewrite(q)

    outer_input("original")
    assert opengrade.flush()
    (sample,) = seen
    assert sample.input == "original"
    assert sample.documents == [{"id": "d1"}]  # documents still bubble up


def test_set_retrieval_documents_from_worker_thread_is_not_captured(sent: Recorder) -> None:
    """ContextVars are not copied into threads the traced function starts."""
    seen: list[opengrade.Sample] = []
    done = threading.Event()

    @opengrade.metric
    def record(s: opengrade.Sample) -> float:
        seen.append(s)
        return 1.0

    @opengrade.trace(name="threaded_docs", metrics=[record])
    def threaded_docs(q: str) -> str:
        def worker() -> None:
            opengrade.set_retrieval_documents([{"id": "from-thread"}])
            done.set()

        threading.Thread(target=worker).start()
        assert done.wait(timeout=2.0)
        return q

    threaded_docs("q")
    assert opengrade.flush()
    (sample,) = seen
    assert sample.documents == []


def test_async_metric_runs_on_worker(sent: Recorder) -> None:
    threads: list[str] = []

    @opengrade.metric
    async def async_len(s: opengrade.Sample) -> float:
        await asyncio.sleep(0)
        threads.append(threading.current_thread().name)
        return float(len(s.output))

    @opengrade.trace(name="with_async_metric", metrics=[async_len])
    def with_async_metric(q: str) -> str:
        return "abc"

    with_async_metric("q")
    assert opengrade.flush()
    assert [s["value"] for s in sent.scores] == [3.0]
    assert threads and threads[0] != threading.current_thread().name


def test_hung_async_metric_times_out_as_failure(
    sent: Recorder, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_production, "METRIC_TIMEOUT_S", 0.05)
    never = threading.Event()

    @opengrade.metric
    async def hung(s: opengrade.Sample) -> float:
        await asyncio.get_running_loop().run_in_executor(None, never.wait, 5)
        return 1.0

    @opengrade.metric
    def after(s: opengrade.Sample) -> float:
        return 1.0

    @opengrade.trace(name="hangs", metrics=[hung, after])
    def hangs(q: str) -> str:
        return q

    caplog.set_level(logging.DEBUG, logger="opengrade")
    hangs("a")
    hangs("b")
    assert opengrade.flush()
    never.set()
    assert len(_warnings(caplog, "production metric 'hung' timed out")) == 1
    assert sorted((s["name"], s.get("label"), s.get("value")) for s in sent.scores) == sorted(
        [
            ("hung", "ERROR", None),
            ("after", None, 1.0),
            ("hung", "ERROR", None),
            ("after", None, 1.0),
        ]
    )
    assert all("TimeoutError" in s["explanation"] for s in sent.scores if s["name"] == "hung")


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

    tracer = trace.get_tracer("opengrade")  # the provider caches it: the one @opengrade.trace uses
    monkeypatch.setattr(tracer, "id_generator", Ids())

    @opengrade.trace(
        name="sampled", metrics=[opengrade.metric(lambda s: 1.0, name="m")], metrics_sample_rate=0.5
    )
    def sampled(q: str) -> str:
        return q

    for i in range(4):
        sampled(str(i))
    assert opengrade.flush()
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

    class Provider:
        def force_flush(self, timeout_millis: int) -> bool:
            calls.append(("spans", timeout_millis / 1000))
            return True

        def shutdown(self) -> None:
            return None

    monkeypatch.setattr(_scores, "time", clock)
    monkeypatch.setattr(_production, "time", clock)
    monkeypatch.setattr(_scores, "_EXIT_DEADLINE", None)
    monkeypatch.setattr(_production, "drain", drain)
    monkeypatch.setattr(_scores, "flush", scores_flush)
    monkeypatch.setattr(_otel, "_PROVIDER", Provider())
    monkeypatch.setattr(_otel, "_EXPORTER", None)

    _production._at_exit()
    _scores._at_exit()
    _otel._at_exit()
    total = _scores.EXIT_FLUSH_TIMEOUT_S
    span_cap = _otel.EXIT_FLUSH_TIMEOUT_MS / 1000
    # metrics +2s, each scores.flush +1s → 4s elapsed before OTel atexit
    remaining_for_spans = total - 4.0
    assert calls == [
        ("metrics", total),
        ("scores", total - 2.0),
        ("scores", total - 3.0),
        ("spans", min(span_cap, remaining_for_spans)),
    ]
    assert min(span_cap, remaining_for_spans) + 4.0 <= total


# --- never raise / never block the caller -------------------------------------------


def _warnings(caplog: pytest.LogCaptureFixture, needle: str) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.levelno == logging.WARNING and needle in r.getMessage()]


def test_full_queue_drops_with_one_warning_and_never_blocks(
    sent: Recorder, caplog: pytest.LogCaptureFixture
) -> None:
    _production._reset_for_tests(workers=1, max_queue=1)
    started = threading.Event()
    release = threading.Event()

    @opengrade.metric
    def slow(s: opengrade.Sample) -> float:
        started.set()
        assert release.wait(10)
        return 1.0

    @opengrade.trace(name="busy", metrics=[slow])
    def busy(q: str) -> str:
        return q

    caplog.set_level(logging.DEBUG, logger="opengrade")
    assert busy("1") == "1"  # taken by the only worker, which then blocks
    assert started.wait(10)
    assert busy("2") == "2"  # fills the queue
    assert busy("3") == "3"  # dropped: caller is not blocked
    assert busy("4") == "4"  # dropped again: no second warning
    assert len(_warnings(caplog, "production metrics queue full")) == 1
    assert _production.dropped() == 2

    release.set()
    assert opengrade.flush()
    assert len(sent.scores) == 2


def test_metric_failures_are_rate_limited(sent: Recorder, caplog: pytest.LogCaptureFixture) -> None:
    @opengrade.metric
    def broken(s: opengrade.Sample) -> float:
        raise ValueError("bad metric")

    @opengrade.trace(name="often", metrics=[broken])
    def often(q: str) -> str:
        return q

    caplog.set_level(logging.DEBUG, logger="opengrade")
    for i in range(3):
        often(str(i))
    assert opengrade.flush()
    assert len(_warnings(caplog, "production metric 'broken' failed")) == 1
    assert len(sent.scores) == 3
    assert all(s["label"] == "ERROR" and s["name"] == "broken" for s in sent.scores)


def test_unexpected_worker_error_is_logged_and_worker_survives(
    sent: Recorder, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = _production.missing_requirement
    calls = {"n": 0}

    def flaky(sample: opengrade.Sample, requires: Any) -> str | None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("internal bug")
        return real(sample, requires)

    monkeypatch.setattr(_production, "missing_requirement", flaky)
    _production._reset_for_tests(workers=1)

    @opengrade.trace(name="job", metrics=[opengrade.metric(lambda s: 1.0, name="m")])
    def job(q: str) -> str:
        return q

    caplog.set_level(logging.DEBUG, logger="opengrade")
    job("a")
    job("b")
    assert opengrade.flush()
    assert len(_warnings(caplog, "internal bug")) == 1
    assert [s["name"] for s in sent.scores] == ["m"]


def test_scheduling_failure_never_reaches_the_caller(
    sent: Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(*args: Any, **kwargs: Any) -> bool:
        raise RuntimeError("cannot start thread")

    monkeypatch.setattr(_production, "_submit", explode)

    @opengrade.trace(name="safe", metrics=[opengrade.metric(lambda s: 1.0, name="m")])
    def safe(q: str) -> str:
        return q

    assert safe("x") == "x"
    assert opengrade.flush()
    assert sent.scores == []


def test_missing_project_warns_once_and_skips(
    sent: Recorder, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENGRADE_PROJECT_ID")

    @opengrade.trace(name="noproj", metrics=[opengrade.metric(lambda s: 1.0, name="m")])
    def noproj(q: str) -> str:
        return q

    caplog.set_level(logging.DEBUG, logger="opengrade")
    assert noproj("a") == "a"
    assert noproj("b") == "b"
    assert opengrade.flush()
    assert len(_warnings(caplog, "production metrics skipped")) == 1
    assert sent.scores == []


def test_after_fork_in_child_resets_pool(sent: Recorder) -> None:
    @opengrade.trace(name="pre_fork", metrics=[opengrade.metric(lambda s: 1.0, name="m")])
    def pre_fork(q: str) -> str:
        return q

    pre_fork("a")
    assert opengrade.flush()
    assert _production._POOL is not None
    old_lock = _production._LOCK
    _production._after_fork_in_child()
    assert _production._POOL is None
    assert _production._LOCK is not old_lock
    pre_fork("b")  # a fresh pool is built lazily
    assert opengrade.flush()
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


# --- configurable metrics workers ---------------------------------------------------


def test_init_metrics_workers_sets_pool_size(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENGRADE_METRICS_WORKERS", raising=False)
    _production._reset_for_tests()
    try:
        opengrade.init(project_slug="demo", instrument=False, metrics_workers=4, force=True)
        pool = _production._pool()
        assert pool._workers == 4
        assert _production._POOL_SIZE == (4, _production.MAX_QUEUE)
    finally:
        _otel._reset_for_tests()
        _production._reset_for_tests()


def test_env_metrics_workers_sets_pool_size(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENGRADE_METRICS_WORKERS", "8")
    _production._reset_for_tests()
    try:
        opengrade.init(project_slug="demo", instrument=False, force=True)
        assert _production._pool()._workers == 8
    finally:
        _otel._reset_for_tests()
        _production._reset_for_tests()


def test_init_metrics_workers_wins_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENGRADE_METRICS_WORKERS", "8")
    _production._reset_for_tests()
    try:
        opengrade.init(project_slug="demo", instrument=False, metrics_workers=3, force=True)
        assert _production._pool()._workers == 3
    finally:
        _otel._reset_for_tests()
        _production._reset_for_tests()


def test_invalid_env_metrics_workers_falls_back(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("OPENGRADE_METRICS_WORKERS", "nope")
    _production._reset_for_tests()
    try:
        with caplog.at_level(logging.WARNING, logger="opengrade"):
            opengrade.init(project_slug="demo", instrument=False, force=True)
        assert _production._pool()._workers == _production.MAX_WORKERS
        assert any("OPENGRADE_METRICS_WORKERS" in r.message for r in caplog.records)
    finally:
        _otel._reset_for_tests()
        _production._reset_for_tests()


def test_invalid_init_metrics_workers_ignored(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.delenv("OPENGRADE_METRICS_WORKERS", raising=False)
    _production._reset_for_tests()
    try:
        with caplog.at_level(logging.WARNING, logger="opengrade"):
            opengrade.init(project_slug="demo", instrument=False, metrics_workers=0, force=True)
        assert _otel._INITIALIZED is True
        assert _production._pool()._workers == _production.MAX_WORKERS
        assert any("metrics_workers ignored" in r.message for r in caplog.records)
    finally:
        _otel._reset_for_tests()
        _production._reset_for_tests()


def test_force_reinit_rebuilds_pool_with_new_workers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENGRADE_METRICS_WORKERS", raising=False)
    _production._reset_for_tests()
    try:
        opengrade.init(project_slug="demo", instrument=False, metrics_workers=2, force=True)
        first = _production._pool()
        assert first._workers == 2
        opengrade.init(project_slug="demo", instrument=False, metrics_workers=5, force=True)
        second = _production._pool()
        assert second is not first
        assert second._workers == 5
        assert first._closed
    finally:
        _otel._reset_for_tests()
        _production._reset_for_tests()


def test_configure_rejects_out_of_range_workers() -> None:
    with pytest.raises(ValueError, match="metrics_workers"):
        _production.configure(workers=0)
    with pytest.raises(ValueError, match="metrics_workers"):
        _production.configure(workers=65)
    with pytest.raises(ValueError, match="metrics_workers"):
        _production.configure(workers=1.5)  # type: ignore[arg-type]
