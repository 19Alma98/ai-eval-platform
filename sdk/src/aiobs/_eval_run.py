from __future__ import annotations

from aiobs._trace import set_attributes


def bind_evaluation(*, experiment_id: str, dataset_item_id: str) -> None:
    """Bind the current span to an experiment dataset item."""
    set_attributes(
        {
            "aiobs.experiment_id": experiment_id,
            "aiobs.dataset_item_id": dataset_item_id,
        }
    )


def _document_has_id(doc: dict[str, object]) -> bool:
    doc_id = doc.get("id")
    if doc_id is None:
        return False
    return bool(str(doc_id).strip())


def set_retrieval_documents(documents: list[dict[str, object]]) -> None:
    """Record retrieved documents on the current span."""
    for index, doc in enumerate(documents):
        if not _document_has_id(doc):
            raise ValueError(f"retrieval document at index {index} must include a non-empty id")
    set_attributes(
        {
            "retrieval.document_count": len(documents),
            "retrieval.documents": documents,
        }
    )
