from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import aiobs
from aiobs import _otel

_shared_exporter: InMemorySpanExporter | None = None


@pytest.fixture(scope="module", autouse=True)
def _reset_otel_before_eval_bind_tests() -> Iterator[None]:
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


def test_bind_evaluation_sets_experiment_and_dataset_item_ids(
    spans: InMemorySpanExporter,
) -> None:
    @aiobs.trace(name="eval-bind", capture_input=False, capture_output=False)
    def run() -> None:
        aiobs.bind_evaluation(experiment_id="exp-abc", dataset_item_id="item-xyz")

    run()
    attrs = dict(spans.get_finished_spans()[0].attributes or {})
    assert attrs["aiobs.experiment_id"] == "exp-abc"
    assert attrs["aiobs.dataset_item_id"] == "item-xyz"


def test_set_retrieval_documents_sets_count_and_payload(
    spans: InMemorySpanExporter,
) -> None:
    documents = [{"id": "doc-1", "title": "A"}, {"id": "doc-2", "text": "body"}]

    @aiobs.trace(name="retrieval", capture_input=False, capture_output=False)
    def run() -> None:
        aiobs.set_retrieval_documents(documents)

    run()
    attrs = dict(spans.get_finished_spans()[0].attributes or {})
    assert attrs["retrieval.document_count"] == 2
    raw = attrs["retrieval.documents"]
    assert isinstance(raw, str)
    parsed = json.loads(raw)
    assert parsed == documents


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
    with pytest.raises(ValueError, match="id"):
        aiobs.set_retrieval_documents(documents)


def test_eval_bind_helpers_exported_in_public_api() -> None:
    assert "bind_evaluation" in aiobs.__all__
    assert "set_retrieval_documents" in aiobs.__all__
    assert callable(aiobs.bind_evaluation)
    assert callable(aiobs.set_retrieval_documents)
