# backend/tests/test_domain_rag_models.py
from __future__ import annotations

import pytest
from pydantic import ValidationError

from opengrade_server.domain.rag_models import ChatTurn, RagChatInput, RagItemMetadata


def test_rag_chat_input_strips_and_defaults_history() -> None:
    parsed = RagChatInput.model_validate({"question": "  Hello?  "})
    assert parsed.question == "Hello?"
    assert parsed.history == []


def test_chat_turn_rejects_bad_role() -> None:
    with pytest.raises(ValidationError):
        ChatTurn.model_validate({"role": "tool", "content": "x"})


def test_chat_turn_rejects_blank_content() -> None:
    with pytest.raises(ValidationError):
        ChatTurn.model_validate({"role": "user", "content": "  "})


def test_metadata_defaults() -> None:
    meta = RagItemMetadata()
    assert meta.expected_doc_ids is None
    assert meta.must_contain is None
    assert meta.answerable is None
