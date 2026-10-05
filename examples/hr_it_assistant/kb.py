from __future__ import annotations

import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
DEFAULT_KB = HERE / "knowledge.json"


def load_knowledge(path: Path | None = None) -> list[dict[str, Any]]:
    target = path or DEFAULT_KB
    data = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("knowledge.json must be a JSON array")
    return data


def retrieve(
    docs: list[dict[str, Any]], question: str, *, top_k: int = 2
) -> list[dict[str, Any]]:
    q = question.lower()
    scored: list[tuple[int, dict[str, Any]]] = []
    for item in docs:
        score = 0
        for kw in item.get("keywords") or []:
            if str(kw).lower() in q:
                score += 2
        for token in (item.get("title") or "").lower().split():
            if len(token) > 3 and token in q:
                score += 1
        for token in (item.get("body") or "").lower().split():
            if len(token) > 5 and token in q:
                score += 1
        if score:
            scored.append((score, item))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in scored[:top_k]]


def iter_gold(docs: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    """Return (question, expected_answer, doc_id) for each gold row."""
    out: list[tuple[str, str, str]] = []
    for doc in docs:
        doc_id = str(doc["id"])
        for g in doc.get("gold") or []:
            out.append((str(g["question"]), str(g["must_contain"]), doc_id))
    return out


def expected_for_question(docs: list[dict[str, Any]], question: str) -> str | None:
    q = question.lower().strip()
    for gq, must, _doc_id in iter_gold(docs):
        if gq.lower().strip() == q:
            return must
    hits = retrieve(docs, question, top_k=1)
    if hits:
        gold = hits[0].get("gold") or []
        if gold:
            return str(gold[0]["must_contain"])
    return None
