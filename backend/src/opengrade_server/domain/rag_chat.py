"""Validation for ``task_type=rag_chat`` dataset items."""

from __future__ import annotations

from typing import Any

from opengrade_server.domain.rag_input import (
    build_chat_input,
    resolve_chat_history,
    resolve_rag_question,
)
from opengrade_server.domain.rag_qa import validate_rag_qa_item


def normalize_chat_input(value: Any) -> dict[str, Any]:
    """Accept structured ``{history, question}`` or a plain question string (empty history)."""
    if isinstance(value, str):
        question = value.strip()
        if not question:
            raise ValueError("rag_chat question must be a non-empty string")
        return build_chat_input(history=[], question=question)
    if not isinstance(value, dict):
        raise ValueError("rag_chat input must be an object with history and question")
    history = resolve_chat_history(value)
    question = resolve_rag_question(value)
    if not question:
        raise ValueError("rag_chat input.question must be a non-empty string")
    return build_chat_input(history=history, question=question)


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
    normalised = normalize_chat_input(input)
    question = normalised["question"]
    cleaned = validate_rag_qa_item(
        input=question,
        expected_output=expected_output,
        metadata=metadata,
    )
    return normalised, cleaned
