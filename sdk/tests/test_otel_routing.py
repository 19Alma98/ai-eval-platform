from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from tests.support.reset import reset_sdk

from opengrade import Opengrade, _otel


@contextmanager
def _span(name: str = "s") -> Iterator[None]:
    with trace.get_tracer("test").start_as_current_span(name):
        yield


@pytest.fixture(autouse=True)
def reset_otel_state(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv("OPENGRADE_PROJECT_ID", raising=False)
    monkeypatch.delenv("OPENGRADE_PROJECT_SLUG", raising=False)
    monkeypatch.delenv("OPENGRADE_DISABLED", raising=False)
    reset_sdk(otel=True)
    yield
    reset_sdk(otel=True)


def _flush_instance(og: Opengrade) -> None:
    provider = og._runtime.provider
    assert provider is not None
    provider.force_flush()


def test_two_instances_route_spans_to_own_exporters() -> None:
    exp_a = InMemorySpanExporter()
    exp_b = InMemorySpanExporter()
    a = Opengrade(project_slug="project-a")
    b = Opengrade(project_slug="project-b")
    a.init_tracing(instrument=False, _span_exporter=exp_a)
    b.init_tracing(instrument=False, _span_exporter=exp_b)

    with a.activate():
        with _span("a-span"):
            pass
    with b.activate():
        with _span("b-span"):
            pass
    _flush_instance(a)
    _flush_instance(b)

    names_a = {s.name for s in exp_a.get_finished_spans()}
    names_b = {s.name for s in exp_b.get_finished_spans()}
    assert names_a == {"a-span"}
    assert names_b == {"b-span"}
    for spans in (exp_a.get_finished_spans(), exp_b.get_finished_spans()):
        for span in spans:
            attrs = span.attributes or {}
            assert _otel._INSTANCE_ATTR not in attrs


def test_asyncio_gather_routes_by_active_instance() -> None:
    exp_a = InMemorySpanExporter()
    exp_b = InMemorySpanExporter()
    a = Opengrade(project_slug="a")
    b = Opengrade(project_slug="b")
    a.init_tracing(instrument=False, _span_exporter=exp_a)
    b.init_tracing(instrument=False, _span_exporter=exp_b)

    async def work(og: Opengrade, name: str) -> None:
        with og.activate():
            with _span(name):
                await asyncio.sleep(0)

    async def main() -> None:
        await asyncio.gather(work(a, "async-a"), work(b, "async-b"))

    asyncio.run(main())
    _flush_instance(a)
    _flush_instance(b)

    assert {s.name for s in exp_a.get_finished_spans()} == {"async-a"}
    assert {s.name for s in exp_b.get_finished_spans()} == {"async-b"}


def test_host_provider_keeps_routing_without_replacement() -> None:
    host = TracerProvider(shutdown_on_exit=False)
    host_exporter = InMemorySpanExporter()
    host.add_span_processor(BatchSpanProcessor(host_exporter))
    trace.set_tracer_provider(host)

    og_exporter = InMemorySpanExporter()
    og = Opengrade(project_slug="demo")
    og.init_tracing(instrument=False, _span_exporter=og_exporter)

    assert trace.get_tracer_provider() is host
    assert og._runtime.owns_provider is False

    with og.activate():
        with _span("routed"):
            pass
    host.force_flush()

    assert any(s.name == "routed" for s in host_exporter.get_finished_spans())
    assert {s.name for s in og_exporter.get_finished_spans()} == {"routed"}


def test_second_instance_instrument_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    import weakref

    exp = InMemorySpanExporter()
    first = Opengrade(project_slug="one")
    second = Opengrade(project_slug="two")
    first.init_tracing(instrument=False, _span_exporter=exp)
    _otel._INSTRUMENTOR_OWNER = weakref.ref(first)
    with caplog.at_level("WARNING", logger="opengrade"):
        second.init_tracing(instrument=["openai"], _span_exporter=InMemorySpanExporter())
    assert any("process-global" in r.message for r in caplog.records)


def _in_plain_thread(fn: object) -> None:
    """Run ``fn`` in a thread that does not inherit ContextVars (no copy_context)."""
    import threading

    errors: list[BaseException] = []

    def run() -> None:
        try:
            fn()  # type: ignore[operator]
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    thread = threading.Thread(target=run)
    thread.start()
    thread.join()
    assert not errors, errors


def test_child_span_follows_parent_instance() -> None:
    exp_a = InMemorySpanExporter()
    exp_b = InMemorySpanExporter()
    a = Opengrade(project_slug="a")
    b = Opengrade(project_slug="b")
    a.init_tracing(instrument=False, _span_exporter=exp_a)
    b.init_tracing(instrument=False, _span_exporter=exp_b)

    with a.activate():
        with _span("root"):
            with b.activate():  # e.g. a library activating its own instance mid-request
                with _span("child"):
                    pass
    _flush_instance(a)
    _flush_instance(b)

    assert {s.name for s in exp_a.get_finished_spans()} == {"root", "child"}
    assert exp_b.get_finished_spans() == ()


def test_plain_thread_uses_the_only_traced_instance() -> None:
    import opengrade

    exp = InMemorySpanExporter()
    og = Opengrade(project_slug="solo")
    og.init_tracing(instrument=False, _span_exporter=exp)

    @opengrade.trace
    def traced() -> int:
        with _span("provider-call"):  # stands in for an auto-instrumented LLM call
            return 1

    _in_plain_thread(traced)
    _flush_instance(og)

    names = {s.name for s in exp.get_finished_spans()}
    assert "provider-call" in names
    assert any(n.endswith("traced") for n in names)


def test_plain_thread_with_several_instances_guesses_nothing() -> None:
    import opengrade

    exp_a = InMemorySpanExporter()
    exp_b = InMemorySpanExporter()
    a = Opengrade(project_slug="a")
    b = Opengrade(project_slug="b")
    a.init_tracing(instrument=False, _span_exporter=exp_a)
    b.init_tracing(instrument=False, _span_exporter=exp_b)

    @opengrade.trace
    def traced() -> int:
        with _span("orphan"):
            return 1

    _in_plain_thread(traced)  # must not raise
    _flush_instance(a)
    _flush_instance(b)
    assert exp_a.get_finished_spans() == ()
    assert exp_b.get_finished_spans() == ()


def test_each_instance_exports_its_own_service_name() -> None:
    exp_a = InMemorySpanExporter()
    exp_b = InMemorySpanExporter()
    a = Opengrade(project_slug="a")
    b = Opengrade(project_slug="b")
    a.init_tracing(service_name="worker-acme", instrument=False, _span_exporter=exp_a)
    b.init_tracing(
        service_name="worker-contoso",
        version="1.2.3",
        instrument=False,
        _span_exporter=exp_b,
    )

    with a.activate(), _span("a"):
        pass
    with b.activate(), _span("b"):
        pass
    _flush_instance(a)
    _flush_instance(b)

    (span_a,) = exp_a.get_finished_spans()
    (span_b,) = exp_b.get_finished_spans()
    assert span_a.resource.attributes["service.name"] == "worker-acme"
    assert span_b.resource.attributes["service.name"] == "worker-contoso"
    assert span_b.resource.attributes["service.version"] == "1.2.3"


def test_router_attached_once_with_several_instances() -> None:
    exp_a = InMemorySpanExporter()
    a = Opengrade(project_slug="a")
    b = Opengrade(project_slug="b")
    c = Opengrade(project_slug="c")
    a.init_tracing(instrument=False, _span_exporter=exp_a)
    b.init_tracing(instrument=False, _span_exporter=InMemorySpanExporter())
    c.init_tracing(instrument=False, _span_exporter=InMemorySpanExporter())

    with a.activate(), _span("once"):
        pass
    _flush_instance(a)
    assert [s.name for s in exp_a.get_finished_spans()] == ["once"]
