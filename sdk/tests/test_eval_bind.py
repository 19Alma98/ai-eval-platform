from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from tests.support.instance import activated, init_og, make_og
from tests.support.reset import reset_sdk

import opengrade
from opengrade import Opengrade

_og: Opengrade | None = None
_shared_exporter: InMemorySpanExporter | None = None


@pytest.fixture(scope="module", autouse=True)
def _reset_otel_before_eval_bind_tests() -> Iterator[None]:
    global _og, _shared_exporter
    reset_sdk(otel=True)
    _og = None
    _shared_exporter = None
    yield
    _og = None
    _shared_exporter = None
    reset_sdk(otel=True)


@pytest.fixture
def spans(monkeypatch: pytest.MonkeyPatch) -> Iterator[InMemorySpanExporter]:
    global _og, _shared_exporter
    if _shared_exporter is None:
        _shared_exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(_shared_exporter))
        trace.set_tracer_provider(provider)
        monkeypatch.setenv("OPENGRADE_PROJECT_ID", "p-eval-bind")
        _og = init_og(project_id="p-eval-bind", instrument=False, _span_exporter=_shared_exporter)
    else:
        _shared_exporter.clear()
    assert _og is not None
    with activated(_og):
        yield _shared_exporter


def test_bind_evaluation_sets_experiment_and_dataset_item_ids(
    spans: InMemorySpanExporter,
) -> None:
    @opengrade.trace(name="eval-bind", capture_input=False, capture_output=False)
    def run() -> None:
        opengrade.bind_evaluation(experiment_id="exp-abc", dataset_item_id="item-xyz")

    run()
    attrs = dict(spans.get_finished_spans()[0].attributes or {})
    assert attrs["opengrade.experiment_id"] == "exp-abc"
    assert attrs["opengrade.dataset_item_id"] == "item-xyz"


def test_set_retrieval_documents_sets_count_and_payload(
    spans: InMemorySpanExporter,
) -> None:
    documents = [{"id": "doc-1", "title": "A"}, {"id": "doc-2", "text": "body"}]

    @opengrade.trace(name="retrieval", capture_input=False, capture_output=False)
    def run() -> None:
        opengrade.set_retrieval_documents(documents)

    run()
    attrs = dict(spans.get_finished_spans()[0].attributes or {})
    assert attrs["retrieval.document_count"] == 2
    assert "retrieval.documents" not in attrs
    assert attrs["retrieval.documents.0.document.id"] == "doc-1"
    assert json.loads(attrs["retrieval.documents.0.document.metadata"]) == {"title": "A"}
    assert attrs["retrieval.documents.1.document.id"] == "doc-2"
    assert attrs["retrieval.documents.1.document.content"] == "body"


@pytest.mark.parametrize(
    "documents",
    [
        [{"title": "missing id"}],
        [{"id": None}],
        [{"id": ""}],
        [{"id": "   "}],
    ],
)
def test_set_retrieval_documents_requires_document_id(documents: list[dict[str, object]]) -> None:
    og = make_og(project_id="p-eval-bind")
    with pytest.raises(ValueError, match="id"):
        with activated(og):
            opengrade.set_retrieval_documents(documents)


def test_eval_bind_helpers_exported_in_public_api() -> None:
    assert "bind_evaluation" in opengrade.__all__
    assert "set_retrieval_documents" in opengrade.__all__
    assert callable(opengrade.bind_evaluation)
    assert callable(opengrade.set_retrieval_documents)
