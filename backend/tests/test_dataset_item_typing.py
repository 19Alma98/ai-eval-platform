from __future__ import annotations

import uuid

from opengrade_server.domain.dataset import DatasetItem
from opengrade_server.domain.rag_models import (
    RagChatInput,
    RagItemContext,
    RagItemMetadata,
    RetrievalDocument,
    dump_context,
    dump_dataset_input,
    dump_metadata,
    parse_context,
    parse_dataset_input,
    parse_metadata,
)


def test_dataset_item_holds_rag_chat_input() -> None:
    item = DatasetItem.create(
        uuid.uuid4(),
        RagChatInput(history=[], question="Q"),
        expected_output="A",
        metadata=RagItemMetadata(expected_doc_ids=["d"]),
    )
    assert isinstance(item.input, RagChatInput)
    assert item.metadata.expected_doc_ids == ["d"]


def test_input_json_roundtrip_chat() -> None:
    model = RagChatInput(history=[], question="Hi")
    raw = dump_dataset_input(model)
    assert raw == {"history": [], "question": "Hi"}
    assert parse_dataset_input(raw) == model


def test_input_json_roundtrip_str() -> None:
    assert parse_dataset_input("Q") == "Q"


def test_context_metadata_json_roundtrip() -> None:
    ctx = RagItemContext(
        documents=[RetrievalDocument(id="d1", text="doc body")],
        search_query="sq",
    )
    meta = RagItemMetadata(expected_doc_ids=["d1"], answerable=True)
    assert parse_context(dump_context(ctx)) == ctx
    assert parse_metadata(dump_metadata(meta)) == meta


def test_context_roundtrip_keeps_operational_fields() -> None:
    raw = {
        "documents": [{"id": "d1", "text": "doc body"}],
        "search_query": "sq",
        "latency_ms": 42.5,
        "prompt_tokens": 10.0,
        "completion_tokens": 5.0,
        "total_tokens": 15.0,
        "cost_usd": 0.001,
        "tool_calls": [{"name": "search", "success": True}],
        "custom_stage": "rerank",
    }
    ctx = parse_context(raw)
    assert ctx is not None
    dumped = dump_context(ctx)
    assert dumped is not None
    assert dumped["latency_ms"] == 42.5
    assert dumped["prompt_tokens"] == 10.0
    assert dumped["completion_tokens"] == 5.0
    assert dumped["total_tokens"] == 15.0
    assert dumped["cost_usd"] == 0.001
    assert dumped["tool_calls"] == [{"name": "search", "success": True}]
    assert dumped["custom_stage"] == "rerank"
    assert parse_context(dumped) == ctx
