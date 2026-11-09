from __future__ import annotations

import pytest
from pydantic import ValidationError

from opengrade.chat import RagChatInput, chat_input


def test_chat_input_from_dict() -> None:
    parsed = chat_input(
        {
            "history": [{"role": "user", "content": "Hi"}],
            "question": "Price?",
        }
    )
    assert isinstance(parsed, RagChatInput)
    assert parsed.question == "Price?"
    assert parsed.history == [{"role": "user", "content": "Hi"}] or (
        parsed.history[0].role == "user" and parsed.history[0].content == "Hi"
    )


def test_chat_input_from_item() -> None:
    class Item:
        input = {"history": [], "question": "Q"}

    assert chat_input(Item()).question == "Q"


def test_chat_input_from_string() -> None:
    parsed = chat_input("Only question")
    assert parsed.history == []
    assert parsed.question == "Only question"


def test_chat_input_rejects_blank() -> None:
    with pytest.raises((ValueError, ValidationError)):
        chat_input({"history": [], "question": "  "})


def test_chat_input_rejects_bad_role() -> None:
    with pytest.raises((ValueError, ValidationError)):
        chat_input({"history": [{"role": "tool", "content": "x"}], "question": "q"})
