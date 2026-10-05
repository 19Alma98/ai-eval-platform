from __future__ import annotations

from typing import Any


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
