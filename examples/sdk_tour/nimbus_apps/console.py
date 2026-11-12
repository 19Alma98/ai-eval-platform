"""Tiny printing helpers so the tour output reads like a walkthrough."""

from __future__ import annotations

import textwrap
from typing import Any


def title(text: str) -> None:
    print(f"\n{'=' * 78}\n{text}\n{'=' * 78}")


def step(number: int | str, text: str) -> None:
    print(f"\n--- Step {number}: {text} " + "-" * max(0, 64 - len(text)))


def note(text: str) -> None:
    print(textwrap.indent(textwrap.fill(" ".join(text.split()), 76), "  > "))


def preview_item_input(raw_input: Any) -> str:
    """Human-readable dataset input: the chat question, not ``ChatTurn(...)`` repr."""
    if isinstance(raw_input, dict):
        question = raw_input.get("question")
        if isinstance(question, str) and question.strip():
            return question
        return str(raw_input)
    question = getattr(raw_input, "question", None)
    if isinstance(question, str) and question.strip():
        return question
    return str(raw_input)