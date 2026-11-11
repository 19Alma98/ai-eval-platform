from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Mapping

from opengrade._run_context import record_documents, record_search_query
from opengrade._trace import set_attributes

logger = logging.getLogger("opengrade")

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


# Where common document objects keep what OpenGrade calls ``id`` / ``text``.
_ID_ALIASES = ("id", "doc_id", "document_id", "id_", "node_id")
_TEXT_ALIASES = ("text", "content", "page_content")
_warned: set[str] = set()


def _warn_once(key: str, message: str, *args: object, exc_info: bool = False) -> None:
    """WARNING the first time, DEBUG afterwards (these run on every traced call)."""
    if key in _warned:
        logger.debug(message, *args, exc_info=exc_info)
        return
    _warned.add(key)
    logger.warning(message, *args, exc_info=exc_info)


def _field(doc: object, names: Iterable[str]) -> object:
    for name in names:
        value = doc.get(name) if isinstance(doc, Mapping) else getattr(doc, name, None)
        if value is not None and not callable(value):
            return value
    return None


def _as_document(doc: object) -> dict[str, object] | None:
    """Normalize a dict or a document object (LangChain, LlamaIndex, your own class).

    None when it carries no id: the retrieval metrics match documents by id.
    """
    metadata = _field(doc, ("metadata",))
    doc_id = _field(doc, _ID_ALIASES)
    if doc_id is None and isinstance(metadata, Mapping):
        doc_id = _field(metadata, _ID_ALIASES)
    if doc_id is None or not str(doc_id).strip():
        return None
    out: dict[str, object] = dict(doc) if isinstance(doc, Mapping) else {}
    out["id"] = str(doc_id).strip()
    for name, aliases in (("text", _TEXT_ALIASES), ("score", ("score",)), ("title", ("title",))):
        value = _field(doc, aliases)
        if value is not None:
            out[name] = value
    if isinstance(metadata, Mapping):
        out["metadata"] = dict(metadata)
    return out


def set_retrieval_documents(documents: Iterable[object]) -> None:
    """Record retrieved documents on the current span as OpenInference flattened attrs.

    Each document is a dict or an object with ``id`` and optionally ``text`` (or
    ``content`` / ``page_content``), ``score``, ``title``, ``metadata``. Like the rest
    of tracing this never raises: a document without an id is skipped with a warning.
    """
    try:
        _set_retrieval_documents(documents)
    except Exception:  # noqa: BLE001 — tracing must never break the host app
        _warn_once(
            "documents_failed",
            "opengrade: set_retrieval_documents failed; documents not recorded",
            exc_info=True,
        )


def _set_retrieval_documents(raw: Iterable[object]) -> None:
    documents: list[dict[str, object]] = []
    for index, item in enumerate(raw):
        doc = _as_document(item)
        if doc is None:
            _warn_once(
                "document_without_id",
                "opengrade: retrieval document at index %d has no id; skipped "
                "(pass dicts or objects with an `id`)",
                index,
            )
            continue
        documents.append(doc)
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
    text = str(query).strip() if query is not None else ""
    if not text:
        _warn_once("empty_search_query", "opengrade: set_search_query got an empty query; ignored")
        return
    record_search_query(text)
    set_attributes({SEARCH_QUERY_ATTR: text, "retrieval.query": text})
