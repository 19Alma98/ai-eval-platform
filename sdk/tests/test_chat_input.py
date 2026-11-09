from __future__ import annotations

import pytest

from opengrade.chat import chat_input


def test_chat_input_from_dict() -> None:
    history, question = chat_input(
        {
            "history": [{"role": "user", "content": "Hi"}],
            "question": "Price?",
        }
    )
    assert history == [{"role": "user", "content": "Hi"}]
    assert question == "Price?"


def test_chat_input_from_item() -> None:
    class Item:
        input = {"history": [], "question": "Q"}

    history, question = chat_input(Item())
    assert history == []
    assert question == "Q"


def test_chat_input_rejects_blank() -> None:
    with pytest.raises(ValueError):
        chat_input({"history": [], "question": "  "})
