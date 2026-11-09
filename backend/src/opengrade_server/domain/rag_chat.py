"""Validation for ``task_type=rag_chat`` dataset items."""

from __future__ import annotations

from typing import Any

from opengrade_server.domain.rag_input import parse_chat_input
from opengrade_server.domain.rag_qa import validate_rag_qa_item


def normalize_chat_input(value: Any) -> dict[str, Any]:
    """Accept structured ``{history, question}`` or a plain question string (empty history)."""
    return parse_chat_input(value).model_dump()


def validate_rag_chat_item(
    *,
    input: Any,
    expected_output: Any,
    metadata: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate one rag_chat item.

    Returns ``(normalised_input, cleaned_metadata)``. Gold fields follow the same
    rules as ``rag_qa`` and apply to the last turn only.
    """
    parsed = parse_chat_input(input)
    normalised = parsed.model_dump()
    question = parsed.question
    cleaned = validate_rag_qa_item(
        input=question,
        expected_output=expected_output,
        metadata=metadata,
    )
    return normalised, cleaned
