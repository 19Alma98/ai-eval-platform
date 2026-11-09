"""Shared helpers for RAG item input: plain ``rag_qa`` strings or ``rag_chat`` objects."""

from __future__ import annotations

from pydantic import ValidationError

from opengrade_server.domain.rag_models import ChatTurn, RagChatInput


def resolve_rag_question(value: str | RagChatInput) -> str:
    """Last-turn question for single-turn judges (works for ``rag_qa`` and ``rag_chat``)."""
    if isinstance(value, str):
        return value.strip()
    return value.question


def build_chat_input(
    *,
    history: list[ChatTurn] | list[dict[str, str]],
    question: str,
) -> RagChatInput:
    try:
        return RagChatInput.model_validate({"history": history, "question": question})
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc


def resolve_chat_history(value: RagChatInput | dict[str, object]) -> list[ChatTurn]:
    """Normalised turns preceding the last question."""
    if isinstance(value, RagChatInput):
        return list(value.history)
    try:
        return list(RagChatInput.model_validate(value).history)
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc


def is_chat_input(value: object) -> bool:
    if isinstance(value, RagChatInput):
        return True
    return isinstance(value, dict) and ("history" in value or "question" in value)


def parse_chat_input(value: str | RagChatInput | dict[str, object]) -> RagChatInput:
    if isinstance(value, RagChatInput):
        return value
    if isinstance(value, str):
        try:
            return RagChatInput(history=[], question=value.strip())
        except ValidationError as exc:
            raise ValueError(str(exc)) from exc
    if isinstance(value, dict):
        try:
            return RagChatInput.model_validate(value)
        except ValidationError as exc:
            raise ValueError(str(exc)) from exc
    raise ValueError("rag_chat input must be an object with history and question")
