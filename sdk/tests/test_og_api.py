"""Everything a traced app needs is on the ``Opengrade`` handle (no module-level calls)."""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import AsyncIterator, Iterator

import httpx2
import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from tests.support.reset import reset_sdk

import opengrade
from opengrade import Opengrade, Settings, _trace, _trace_attrs
from opengrade._context import ensure_project
from opengrade._opengrade import _CURRENT
from opengrade.experiment.dataset import _infer_task_type


@pytest.fixture(autouse=True)
def reset_otel_state(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name in ("OPENGRADE_PROJECT", "OPENGRADE_PROJECT_ID", "OPENGRADE_PROJECT_SLUG"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("OPENGRADE_DISABLED", raising=False)
    reset_sdk(otel=True)
    yield
    reset_sdk(otel=True)


def _traced(slug: str) -> tuple[Opengrade, InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    og = Opengrade(project_slug=slug)
    og.init_tracing(instrument=False, _span_exporter=exporter)
    return og, exporter


def _names(og: Opengrade, exporter: InMemorySpanExporter) -> list[str]:
    provider = og._runtime.provider
    assert provider is not None
    provider.force_flush()
    return sorted(s.name for s in exporter.get_finished_spans())


def test_og_trace_and_span_route_to_their_instance_without_activate() -> None:
    a, exp_a = _traced("a")
    b, exp_b = _traced("b")

    @a.trace
    def ask_a(q: str) -> str:
        with a.span("retrieve", kind="RETRIEVER", input=q) as s:
            a.set_retrieval_documents([{"id": "d1", "text": "t"}])
            s.set_output(["d1"])
        a.set_user("u-1")
        a.set_tags("beta")
        a.set_metadata(plan="pro")
        assert a.current_trace_id() is not None
        return q.upper()

    @b.trace(name="ask-b", kind="AGENT")
    def ask_b(q: str) -> str:
        return q

    assert ask_a("hi") == "HI"
    assert ask_b("yo") == "yo"
    assert _CURRENT.get() is None  # nothing left activated

    assert _names(b, exp_b) == ["ask-b"]
    spans = {s.name: s for s in exp_a.get_finished_spans()}
    assert _names(a, exp_a) == sorted(spans) and len(spans) == 2
    root = next(s for name, s in spans.items() if name != "retrieve")
    attrs = dict(root.attributes or {})
    assert attrs["user.id"] == "u-1"
    assert json.loads(attrs["metadata"])["plan"] == "pro"
    assert dict(spans["retrieve"].attributes or {})["retrieval.document_count"] == 1


def test_og_trace_supports_async_and_generators_without_leaking_current() -> None:
    og, exporter = _traced("gen")

    @og.trace(name="stream")
    def stream() -> Iterator[str]:
        yield "a"
        yield "b"

    @og.trace(name="astream")
    async def astream() -> AsyncIterator[str]:
        yield "x"

    @og.trace(name="acall")
    async def acall() -> str:
        async with og.span("tool", kind="TOOL"):
            pass
        return "ok"

    seen = []
    for chunk in stream():
        assert _CURRENT.get() is None  # the consumer's code is not inside the instance
        seen.append(chunk)

    async def consume() -> list[str]:
        return [chunk async for chunk in astream()]

    assert seen == ["a", "b"]
    assert asyncio.run(consume()) == ["x"]
    assert asyncio.run(acall()) == "ok"
    assert inspect.isgeneratorfunction(stream) and inspect.iscoroutinefunction(acall)
    assert _names(og, exporter) == ["acall", "astream", "stream", "tool"]


def test_og_trace_starts_tracing_on_first_call(monkeypatch: pytest.MonkeyPatch) -> None:
    started: list[Opengrade] = []
    monkeypatch.setattr(
        Opengrade, "init_tracing", lambda self, **kwargs: started.append(self), raising=True
    )
    og = Opengrade(project="demo")

    @og.trace
    def ask(q: str) -> str:
        return q

    assert started == []  # decorating does nothing
    assert ask("a") == "a" and ask("b") == "b"
    with og.span("block"):
        pass
    assert started == [og]


def test_og_exposes_the_tracing_helpers_with_the_same_signatures() -> None:
    pairs = {
        "span": _trace.span.__init__,
        "set_input": _trace.set_input,
        "set_output": _trace.set_output,
        "set_attribute": _trace.set_attribute,
        "set_attributes": _trace.set_attributes,
        "set_error": _trace.set_error,
        "current_trace_id": _trace.current_trace_id,
        "set_user": _trace_attrs.set_user,
        "set_session": _trace_attrs.set_session,
        "set_tags": _trace_attrs.set_tags,
        "set_metadata": _trace_attrs.set_metadata,
        "using_attributes": _trace_attrs.using_attributes,
        "set_retrieval_documents": opengrade.set_retrieval_documents,
        "set_search_query": opengrade.set_search_query,
    }
    for name, module_level in pairs.items():
        expected = [p for p in inspect.signature(module_level).parameters if p != "self"]
        got = [p for p in inspect.signature(getattr(Opengrade, name)).parameters if p != "self"]
        assert got == expected, name


# --- project by name ---------------------------------------------------------------------


def test_project_name_sets_the_slug() -> None:
    assert Opengrade(project="My App").settings.project_slug == "my-app"
    assert Opengrade(Settings(project="My App")).settings.project_slug == "my-app"
    # An explicit id / slug wins: nothing is derived (or created) from the name.
    assert Opengrade(project="My App", project_slug="other").settings.project_slug == "other"


def test_project_name_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENGRADE_PROJECT", "From Env")
    assert Opengrade().settings.project_slug == "from-env"


class _Platform:
    """Minimal project API: list by slug / name, create."""

    def __init__(self, existing: bool = False, down: bool = False) -> None:
        self.project = {"id": "p-1", "name": "My App", "slug": "my-app"} if existing else None
        self.down = down
        self.created = 0

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        if self.down:
            raise httpx2.ConnectError("down")
        if request.method == "POST":
            self.created += 1
            body = json.loads(request.content)
            self.project = {"id": "p-1", "name": body["name"], "slug": body["slug"]}
            return httpx2.Response(201, json=self._row())
        return httpx2.Response(200, json=[self._row()] if self.project else [])

    def _row(self) -> dict[str, object]:
        assert self.project is not None
        stamp = "2026-01-01T00:00:00Z"
        return {**self.project, "description": None, "created_at": stamp, "updated_at": stamp}


def _with_platform(og: Opengrade, platform: _Platform) -> None:
    og._runtime.client = opengrade.Client(
        "http://platform", transport=httpx2.MockTransport(platform)
    )


@pytest.mark.parametrize("existing", [False, True])
def test_named_project_is_found_or_created_once(existing: bool) -> None:
    platform = _Platform(existing=existing)
    og = Opengrade(project="My App")
    _with_platform(og, platform)

    assert ensure_project(og._runtime) == "p-1"
    assert ensure_project(og._runtime) == "p-1"
    assert platform.created == (0 if existing else 1)
    assert og.settings.project_id == "p-1"
    assert og.client._project_id == "p-1"  # the control plane is bound too


def test_named_project_is_retried_after_the_platform_was_down() -> None:
    platform = _Platform(down=True)
    og = Opengrade(project="My App")
    _with_platform(og, platform)

    assert ensure_project(og._runtime) is None  # quiet: the caller reports it
    platform.down = False
    assert og.client._project_id == "p-1"


def test_slug_of_a_missing_project_is_not_created() -> None:
    platform = _Platform()
    og = Opengrade(project_slug="my-app")
    _with_platform(og, platform)

    assert ensure_project(og._runtime) is None
    assert og.client._project_id is None
    assert platform.created == 0


# --- evaluate: task type of inline rows --------------------------------------------------


@pytest.mark.parametrize(
    ("rows", "expected"),
    [
        ([{"input": "2+2", "expected_output": "4"}], "generic"),
        ([{"input": "q", "metadata": {"expected_doc_ids": ["d1"]}}, {"input": "q2"}], "rag_qa"),
        ([{"input": {"history": [], "question": "q"}}], "rag_chat"),
    ],
)
def test_task_type_is_inferred_from_inline_rows(
    rows: list[dict[str, object]], expected: str
) -> None:
    assert _infer_task_type(rows) == expected
