"""Shared helpers for RAG item input: plain ``rag_qa`` strings or ``rag_chat`` objects."""

from __future__ import annotations

from typing import Any

CHAT_ROLES = frozenset({"user", "assistant", "system"})


def resolve_rag_question(value: Any) -> str:
    """Last-turn question for single-turn judges (works for ``rag_qa`` and ``rag_chat``)."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        question = value.get("question")
        if isinstance(question, str) and question.strip():
            return question.strip()
        # Nested under input-shaped payloads from some importers / promotions.
        nested = value.get("input")
        if isinstance(nested, dict):
            return resolve_rag_question(nested)
        if isinstance(nested, str) and nested.strip():
            return nested.strip()
    return ""


def resolve_chat_history(value: Any) -> list[dict[str, str]]:
    """Normalised ``[{role, content}, ...]`` turns preceding the last question."""
    if not isinstance(value, dict):
        return []
    raw = value.get("history")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("rag_chat history must be a list of {role, content} turns")
    out: list[dict[str, str]] = []
    for index, turn in enumerate(raw):
        if not isinstance(turn, dict):
            raise ValueError(f"rag_chat history[{index}] must be an object")
        role = turn.get("role")
        content = turn.get("content")
        if not isinstance(role, str) or role.strip() not in CHAT_ROLES:
            raise ValueError(
                f"rag_chat history[{index}].role must be one of {', '.join(sorted(CHAT_ROLES))}"
            )
        if not isinstance(content, str) or not content.strip():
            raise ValueError(f"rag_chat history[{index}].content must be a non-empty string")
        out.append({"role": role.strip(), "content": content.strip()})
    return out


def is_chat_input(value: Any) -> bool:
    return isinstance(value, dict) and (
        "history" in value or (isinstance(value.get("question"), str) and "question" in value)
    )


def build_chat_input(*, history: list[dict[str, str]], question: str) -> dict[str, Any]:
    cleaned_question = question.strip()
    if not cleaned_question:
        raise ValueError("rag_chat question must be a non-empty string")
    return {"history": list(history), "question": cleaned_question}
