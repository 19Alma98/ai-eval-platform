from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

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
    text: str = ""


class RagItemContext(BaseModel):
    """Per-item eval context: retrieval plus operational fields from traces / the SDK."""

    model_config = ConfigDict(extra="allow")

    documents: list[RetrievalDocument] = Field(default_factory=list)
    search_query: str | None = None
    latency_ms: float | None = None
    prompt_tokens: float | None = None
    completion_tokens: float | None = None
    total_tokens: float | None = None
    cost_usd: float | None = None
    tool_calls: list[dict[str, object]] | None = None


class RagItemMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    expected_doc_ids: list[str] | None = None
    must_contain: list[str] | None = None
    answerable: bool | None = None


def parse_dataset_input(value: object) -> str | RagChatInput:
    if isinstance(value, str):
        return value
    if isinstance(value, RagChatInput):
        return value
    if isinstance(value, dict):
        return RagChatInput.model_validate(value)
    raise ValueError("dataset input must be a string or RagChatInput object")


def dump_dataset_input(value: str | RagChatInput) -> str | dict[str, object]:
    if isinstance(value, str):
        return value
    return value.model_dump(mode="json")


def parse_context(value: object | None) -> RagItemContext | None:
    if value is None:
        return None
    if isinstance(value, RagItemContext):
        return value
    if isinstance(value, dict):
        return RagItemContext.model_validate(value)
    raise ValueError("dataset context must be a RagItemContext object or mapping")


def dump_context(value: RagItemContext | None) -> dict[str, object] | None:
    if value is None:
        return None
    return value.model_dump(mode="json", exclude_none=True)


def parse_metadata(value: object | None) -> RagItemMetadata:
    if value is None:
        return RagItemMetadata()
    if isinstance(value, RagItemMetadata):
        return value
    if isinstance(value, dict):
        return RagItemMetadata.model_validate(value)
    raise ValueError("dataset metadata must be a RagItemMetadata object or mapping")


def dump_metadata(value: RagItemMetadata, *, exclude_none: bool = False) -> dict[str, object]:
    return value.model_dump(mode="json", exclude_none=exclude_none)


def metadata_as_mapping(value: RagItemMetadata) -> dict[str, object]:
    """Dict view of typed metadata for merges and dotted-path lookups."""
    return dump_metadata(value)
