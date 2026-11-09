"""Helpers for conversational RAG dataset items (``task_type=rag_chat``)."""

from __future__ import annotations

from typing import Any


def chat_input(item: Any) -> tuple[list[dict[str, str]], str]:
    """Return ``(history, question)`` from a dataset item or raw input value.

    Accepts ``item.input`` shaped as ``{"history": [...], "question": "..."}``
    or a plain string question (empty history).
    """
    value = getattr(item, "input", item)
    if isinstance(value, str):
        question = value.strip()
        if not question:
            raise ValueError("chat question must be a non-empty string")
        return [], question
    if not isinstance(value, dict):
        raise ValueError("chat input must be a dict with history and question, or a string")
    question = value.get("question")
    if not isinstance(question, str) or not question.strip():
        raise ValueError("chat input.question must be a non-empty string")
    history_raw = value.get("history") or []
    if not isinstance(history_raw, list):
        raise ValueError("chat input.history must be a list")
    history: list[dict[str, str]] = []
    for index, turn in enumerate(history_raw):
        if not isinstance(turn, dict):
            raise ValueError(f"chat history[{index}] must be an object")
        role = turn.get("role")
        content = turn.get("content")
        if not isinstance(role, str) or not role.strip():
            raise ValueError(f"chat history[{index}].role must be a non-empty string")
        if not isinstance(content, str) or not content.strip():
            raise ValueError(f"chat history[{index}].content must be a non-empty string")
        history.append({"role": role.strip(), "content": content.strip()})
    return history, question.strip()
