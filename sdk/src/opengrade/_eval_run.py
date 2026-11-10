from __future__ import annotations

import json

from opengrade._run_context import record_documents, record_search_query
from opengrade._trace import set_attributes

SEARCH_QUERY_ATTR = "opengrade.retrieval.query"


def bind_evaluation(*, experiment_id: str, dataset_item_id: str, repeat: int = 0) -> None:
    """Bind the current span to an experiment dataset item (and repeat, when > 0)."""
    attributes: dict[str, object] = {
        "opengrade.experiment_id": experiment_id,
        "opengrade.dataset_item_id": dataset_item_id,
    }
    if repeat:
        attributes["opengrade.repeat"] = repeat
    set_attributes(attributes)


def _document_has_id(doc: dict[str, object]) -> bool:
    doc_id = doc.get("id")
    if doc_id is None:
        return False
    return bool(str(doc_id).strip())


def set_retrieval_documents(documents: list[dict[str, object]]) -> None:
    """Record retrieved documents on the current span as OpenInference flattened attrs."""
    for index, doc in enumerate(documents):
        if not _document_has_id(doc):
            raise ValueError(f"retrieval document at index {index} must include a non-empty id")
    record_documents([dict(doc) for doc in documents])
    attributes: dict[str, object] = {"retrieval.document_count": len(documents)}
    for index, doc in enumerate(documents):
        prefix = f"retrieval.documents.{index}.document"
        attributes[f"{prefix}.id"] = str(doc["id"]).strip()
        text = doc.get("text")
        if text is not None and str(text):
            attributes[f"{prefix}.content"] = str(text)
        score = doc.get("score")
        if score is not None:
            attributes[f"{prefix}.score"] = score
        metadata: dict[str, object] = {}
        if "metadata" in doc and isinstance(doc["metadata"], dict):
            metadata.update(doc["metadata"])
        title = doc.get("title")
        if title is not None and str(title).strip():
            metadata.setdefault("title", str(title).strip())
        if metadata:
            attributes[f"{prefix}.metadata"] = json.dumps(metadata, default=str)
    set_attributes(attributes)


def set_search_query(query: str) -> None:
    """Record the standalone / rewritten retrieval query for conversation judges.

    Sets ``opengrade.retrieval.query`` on the current span and captures it into the
    experiment / production context as ``search_query``.
    """
    text = str(query).strip()
    if not text:
        raise ValueError("search query must be a non-empty string")
    record_search_query(text)
    set_attributes({SEARCH_QUERY_ATTR: text, "retrieval.query": text})
