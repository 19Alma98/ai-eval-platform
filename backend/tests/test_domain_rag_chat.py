from __future__ import annotations

import pytest

from opengrade_server.domain.rag_chat import validate_rag_chat_item
from opengrade_server.domain.rag_input import resolve_rag_question
from opengrade_server.evaluation.judges import prompts


def test_validate_rag_chat_ok() -> None:
    normalised, meta = validate_rag_chat_item(
        input={
            "history": [
                {"role": "user", "content": "Do we have Pro?"},
                {"role": "assistant", "content": "Yes."},
            ],
            "question": "How much does it cost?",
        },
        expected_output="8 dollars",
        metadata={"expected_doc_ids": ["plans"]},
    )
    assert normalised["question"] == "How much does it cost?"
    assert len(normalised["history"]) == 2
    assert meta["expected_doc_ids"] == ["plans"]


def test_validate_rejects_bad_role() -> None:
    with pytest.raises(ValueError, match="role"):
        validate_rag_chat_item(
            input={
                "history": [{"role": "tool", "content": "x"}],
                "question": "q",
            },
            expected_output="a",
            metadata={"expected_doc_ids": ["d"]},
        )


def test_question_text_prefers_last_turn() -> None:
    value = {"history": [], "question": "What is PTO?"}
    assert resolve_rag_question(value) == "What is PTO?"
    assert prompts.question_text(value) == "What is PTO?"
    assert prompts.question_text("plain") == "plain"
