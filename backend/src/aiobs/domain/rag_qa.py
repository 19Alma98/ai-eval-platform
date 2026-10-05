from __future__ import annotations

from typing import Any

EXPECTED_DOC_IDS_KEY = "expected_doc_ids"
MUST_CONTAIN_KEY = "must_contain"


def _normalize_string_list(value: Any, *, field: str) -> list[str]:
    if value is None:
        raise ValueError(f"{field} is required")
    if isinstance(value, str):
        parts = [p.strip() for p in value.replace(",", "|").split("|") if p.strip()]
        if not parts:
            raise ValueError(f"{field} must be non-empty")
        return parts
    if isinstance(value, list):
        out = [str(x).strip() for x in value if str(x).strip()]
        if not out:
            raise ValueError(f"{field} must be non-empty")
        return out
    raise ValueError(f"{field} must be a list or pipe-separated string")


def normalize_expected_doc_ids(value: Any) -> list[str]:
    return _normalize_string_list(value, field=EXPECTED_DOC_IDS_KEY)


def normalize_must_contain(value: Any) -> list[str]:
    return _normalize_string_list(value, field=MUST_CONTAIN_KEY)


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

    if MUST_CONTAIN_KEY in cleaned:
        raw = cleaned.get(MUST_CONTAIN_KEY)
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            cleaned.pop(MUST_CONTAIN_KEY, None)
        else:
            cleaned[MUST_CONTAIN_KEY] = normalize_must_contain(raw)
    return cleaned
