from __future__ import annotations

import json
import re
from typing import Any

# OpenInference flattens documents as ``{prefix}.{N}.document.{field}``.
_FLAT_DOCUMENT = re.compile(r"^(\d+)\.document\.(.+)$")
_METADATA_ID_KEYS = ("doc_id", "document_id", "node_id", "id")
_METADATA_TITLE_KEYS = ("title", "file_name")


def flattened_documents(attributes: dict[str, Any], prefix: str) -> list[dict[str, Any]] | None:
    """Documents from OpenInference flattened attributes, or None if there are none."""
    head = f"{prefix}."
    rows: dict[int, dict[str, Any]] = {}
    for key, value in attributes.items():
        if not key.startswith(head):
            continue
        match = _FLAT_DOCUMENT.match(key[len(head) :])
        if match is not None:
            rows.setdefault(int(match.group(1)), {})[match.group(2)] = value
    if not rows:
        return None
    return normalize_documents([_from_openinference(rows[i]) for i in sorted(rows)])


def _from_openinference(fields: dict[str, Any]) -> dict[str, Any]:
    metadata = fields.get("metadata")
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except json.JSONDecodeError:
            metadata = None
    if not isinstance(metadata, dict):
        metadata = {}
    doc_id = fields.get("id")
    if doc_id is None or not str(doc_id).strip():
        doc_id = next((metadata[k] for k in _METADATA_ID_KEYS if metadata.get(k)), None)
    title = next((metadata[k] for k in _METADATA_TITLE_KEYS if metadata.get(k)), None)
    return {"id": doc_id, "title": title, "text": fields.get("content")}


def normalize_documents(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    out: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        doc_id = item.get("id")
        if doc_id is None:
            continue
        id_str = str(doc_id).strip()
        if not id_str:
            continue
        doc: dict[str, Any] = {"id": id_str}
        if "title" in item and item["title"] is not None:
            title = str(item["title"]).strip()
            if title:
                doc["title"] = title
        if "text" in item and item["text"] is not None:
            text = str(item["text"])
            if text:
                doc["text"] = text
        out.append(doc)
    return out
