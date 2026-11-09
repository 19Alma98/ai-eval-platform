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


class RetrievalDocument(BaseModel):
    id: str
    text: str


class RagItemContext(BaseModel):
    documents: list[RetrievalDocument] = Field(default_factory=list)
    search_query: str | None = None


class RagItemMetadata(BaseModel):
    expected_doc_ids: list[str] | None = None
    must_contain: list[str] | None = None
    answerable: bool | None = None
