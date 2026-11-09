"""Validation for ``task_type=rag_chat`` dataset items."""

from __future__ import annotations

from opengrade_server.domain.rag_input import parse_chat_input
from opengrade_server.domain.rag_models import RagChatInput, RagItemMetadata
from opengrade_server.domain.rag_qa import validate_rag_qa_item


def normalize_chat_input(value: str | RagChatInput | dict[str, object]) -> RagChatInput:
    """Accept structured ``{history, question}`` or a plain question string (empty history)."""
    return parse_chat_input(value)


def validate_rag_chat_item(
    *,
    input: str | RagChatInput | dict[str, object],
    expected_output: str | None,
    metadata: RagItemMetadata | dict[str, object],
) -> tuple[RagChatInput, RagItemMetadata]:
    """Validate one rag_chat item.

    Returns ``(normalised_input, cleaned_metadata)``. Gold fields follow the same
    rules as ``rag_qa`` and apply to the last turn only.
    """
    normalised = normalize_chat_input(input)
    cleaned = validate_rag_qa_item(
        input=normalised.question,
        expected_output=expected_output,
        metadata=metadata,
    )
    return normalised, cleaned
