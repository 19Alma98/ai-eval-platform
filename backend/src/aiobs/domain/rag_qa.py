from __future__ import annotations

from typing import Any

EXPECTED_DOC_IDS_KEY = "expected_doc_ids"


def normalize_expected_doc_ids(value: Any) -> list[str]:
    if value is None:
        raise ValueError("expected_doc_ids is required")
    if isinstance(value, str):
        parts = [p.strip() for p in value.replace(",", "|").split("|") if p.strip()]
        if not parts:
            raise ValueError("expected_doc_ids must be non-empty")
        return parts
    if isinstance(value, list):
        out = [str(x).strip() for x in value if str(x).strip()]
        if not out:
            raise ValueError("expected_doc_ids must be non-empty")
        return out
    raise ValueError("expected_doc_ids must be a list or pipe-separated string")


def validate_rag_qa_item(
    *,
    input: Any,
    expected_output: Any,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(input, str) or not input.strip():
        raise ValueError("rag_qa input (question) must be a non-empty string")
    if not isinstance(expected_output, str) or not expected_output.strip():
        raise ValueError("rag_qa expected_output (expected_answer) must be a non-empty string")
    ids = normalize_expected_doc_ids(metadata.get(EXPECTED_DOC_IDS_KEY))
    cleaned = dict(metadata)
    cleaned[EXPECTED_DOC_IDS_KEY] = ids
    return cleaned
