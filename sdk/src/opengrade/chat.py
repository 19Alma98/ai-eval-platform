"""Helpers for conversational RAG dataset items (``task_type=rag_chat``)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

ChatRole = Literal["user", "assistant", "system"]


class ChatTurn(BaseModel):
    role: ChatRole
    content: str

    @field_validator("role", mode="before")
    @classmethod
    def _strip_role(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("content", mode="before")
    @classmethod
    def _strip_content(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("content")
    @classmethod
    def _non_empty_content(cls, value: str) -> str:
        if not value:
            raise ValueError("content must be a non-empty string")
        return value


class RagChatInput(BaseModel):
    history: list[ChatTurn] = Field(default_factory=list)
    question: str

    @field_validator("question", mode="before")
    @classmethod
    def _strip_question(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("question")
    @classmethod
    def _non_empty_question(cls, value: str) -> str:
        if not value:
            raise ValueError("question must be a non-empty string")
        return value


def chat_input(item: object) -> RagChatInput:
    """Return parsed chat input from a dataset item or raw input value.

    Accepts ``item.input`` shaped as ``{"history": [...], "question": "..."}``
    or a plain string question (empty history).
    """
    value = getattr(item, "input", item)
    if isinstance(value, RagChatInput):
        return value
    if isinstance(value, str):
        return RagChatInput(history=[], question=value.strip())
    if isinstance(value, dict):
        return RagChatInput.model_validate(value)
    raise ValueError("chat input must be a dict with history and question, or a string")
