from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from opengrade_server.domain.rag_models import RagItemMetadata

EXPECTED_DOC_IDS_KEY = "expected_doc_ids"
MUST_CONTAIN_KEY = "must_contain"
# Item labels saying whether the knowledge base answers the question (refusal judge).
ANSWERABLE_KEYS = ("answerable", "expected_refusal", "should_refuse")


def parse_bool(value: Any) -> bool | None:
    """Lenient boolean for labels coming from JSON or CSV ("false", "no", 0, ...)."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("true", "yes", "y", "1", "si", "sì"):
            return True
        if text in ("false", "no", "n", "0"):
            return False
    return None


def label_answerable(metadata: Mapping[str, Any] | RagItemMetadata) -> bool | None:
    """``metadata.answerable`` wins; else the inverse of ``expected_refusal``/``should_refuse``."""
    if isinstance(metadata, RagItemMetadata):
        if metadata.answerable is not None:
            return metadata.answerable
        return None
    flag = parse_bool(metadata.get("answerable"))
    if flag is not None:
        return flag
    for key in ("expected_refusal", "should_refuse"):
        refuse = parse_bool(metadata.get(key))
        if refuse is not None:
            return not refuse
    return None


def _normalize_string_list(value: Any, *, field: str, split_commas: bool) -> list[str]:
    if value is None:
        raise ValueError(f"{field} is required")
    if isinstance(value, str):
        text = value.replace(",", "|") if split_commas else value
        parts = [p.strip() for p in text.split("|") if p.strip()]
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
    return _normalize_string_list(value, field=EXPECTED_DOC_IDS_KEY, split_commas=True)


def normalize_must_contain(value: Any) -> list[str]:
    # Phrases may contain commas ("$1,000"), so only the pipe separates them.
    return _normalize_string_list(value, field=MUST_CONTAIN_KEY, split_commas=False)


def _metadata_as_dict(metadata: RagItemMetadata | Mapping[str, object]) -> dict[str, Any]:
    if isinstance(metadata, RagItemMetadata):
        return metadata.model_dump(exclude_none=True)
    return dict(metadata)


def validate_rag_qa_item(
    *,
    input: str,
    expected_output: str | None,
    metadata: RagItemMetadata | dict[str, object],
) -> RagItemMetadata:
    """Validate and normalise one rag_qa item; returns the cleaned metadata.

    Questions the knowledge base does not answer (``metadata.answerable: false`` or
    ``expected_refusal: true``) test refusals: they have no gold documents, so
    ``expected_doc_ids`` may be omitted (retrieval metrics then skip the item) and
    ``expected_output`` too (the refusal judge reads the label). Every other item
    needs both.
    """
    if not isinstance(input, str) or not input.strip():
        raise ValueError("rag_qa input (question) must be a non-empty string")
    cleaned = _metadata_as_dict(metadata)
    unanswerable = label_answerable(cleaned) is False
    if expected_output is not None or not unanswerable:
        if not isinstance(expected_output, str) or not expected_output.strip():
            raise ValueError("rag_qa expected_output (expected_answer) must be a non-empty string")
    raw_ids = cleaned.get(EXPECTED_DOC_IDS_KEY)
    expected_doc_ids: list[str] | None
    if unanswerable and (raw_ids is None or raw_ids == [] or raw_ids == ""):
        expected_doc_ids = None
    else:
        expected_doc_ids = normalize_expected_doc_ids(raw_ids)

    must_contain: list[str] | None = None
    if MUST_CONTAIN_KEY in cleaned:
        raw = cleaned.get(MUST_CONTAIN_KEY)
        if raw is not None and not (isinstance(raw, str) and not raw.strip()):
            must_contain = normalize_must_contain(raw)

    answerable = label_answerable(cleaned)
    return RagItemMetadata(
        expected_doc_ids=expected_doc_ids,
        must_contain=must_contain,
        answerable=answerable,
    )
