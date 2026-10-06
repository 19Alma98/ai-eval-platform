from __future__ import annotations

import uuid
from datetime import UTC, datetime

from aiobs.domain.trace import Span, Trace
from aiobs.tracing.run_binding import (
    build_output_from_trace,
    extract_run_binding,
    traces_for_output_binding,
)


def test_extract_run_binding_from_chain_span() -> None:
    exp_id = uuid.uuid4()
    item_id = uuid.uuid4()
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = datetime(2024, 1, 1, 0, 0, 1, tzinfo=UTC)
    chain = Span(
        id=uuid.uuid4(),
        span_id="a" * 16,
        parent_span_id=None,
        name="chain",
        kind="CHAIN",
        start_time=start,
        end_time=end,
        status="ok",
        attributes={
            "aiobs.experiment_id": str(exp_id),
            "aiobs.dataset_item_id": str(item_id),
        },
    )
    trace = Trace(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        trace_id="b" * 32,
        name="chain",
        status="ok",
        start_time=start,
        end_time=end,
        output="answer",
        spans=(chain,),
    )
    assert extract_run_binding(trace) == (exp_id, item_id)


def test_build_output_from_trace_sets_metadata_and_context() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = datetime(2024, 1, 1, 0, 0, 1, tzinfo=UTC)
    retriever = Span(
        id=uuid.uuid4(),
        span_id="c" * 16,
        parent_span_id="a" * 16,
        name="retrieve",
        kind="RETRIEVER",
        start_time=start,
        end_time=end,
        status="ok",
        attributes={
            "retrieval.documents": [{"id": "d1", "text": "body"}],
        },
    )
    trace = Trace(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        trace_id="trace-1",
        name="rag",
        status="ok",
        start_time=start,
        end_time=end,
        output="final",
        spans=(retriever,),
    )
    payload = build_output_from_trace(trace)
    assert payload["actual_output"] == "final"
    assert payload["metadata"] == {"source_trace_id": "trace-1"}
    assert payload["context"]["documents"][0]["id"] == "d1"
    assert payload["context"]["latency_ms"] == 1000.0


def _chain_trace(*, trace_id: str, with_spans: bool) -> Trace:
    exp_id = uuid.uuid4()
    item_id = uuid.uuid4()
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = datetime(2024, 1, 1, 0, 0, 1, tzinfo=UTC)
    chain = Span(
        id=uuid.uuid4(),
        span_id="a" * 16,
        parent_span_id=None,
        name="chain",
        kind="CHAIN",
        start_time=start,
        end_time=end,
        status="ok",
        attributes={
            "aiobs.experiment_id": str(exp_id),
            "aiobs.dataset_item_id": str(item_id),
        },
    )
    return Trace(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        trace_id=trace_id,
        name="chain",
        status="ok",
        start_time=start,
        end_time=end,
        output="answer",
        spans=(chain,) if with_spans else (),
    )


def test_traces_for_output_binding_prefers_payload_when_saved_dropped_spans() -> None:
    payload = _chain_trace(trace_id="c" * 32, with_spans=True)
    saved = Trace(
        id=payload.id,
        project_id=payload.project_id,
        trace_id=payload.trace_id,
        name=payload.name,
        status=payload.status,
        start_time=payload.start_time,
        end_time=payload.end_time,
        output=payload.output,
        spans=(),
    )
    chosen = traces_for_output_binding([payload], [saved])
    assert extract_run_binding(chosen[0]) is not None


def test_traces_for_output_binding_prefers_saved_when_it_has_binding() -> None:
    payload = _chain_trace(trace_id="d" * 32, with_spans=True)
    saved = _chain_trace(trace_id="d" * 32, with_spans=True)
    chosen = traces_for_output_binding([payload], [saved])
    assert chosen[0] is saved
