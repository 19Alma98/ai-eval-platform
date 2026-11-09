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
