from __future__ import annotations

import uuid

from opengrade_server.domain.dataset import DatasetItem
from opengrade_server.domain.rag_models import (
    RagChatInput,
    RagItemMetadata,
    dump_dataset_input,
    parse_dataset_input,
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
