"""Toy RAG pipeline used by the CI regression-gate example.

Deterministic on purpose (keyword retriever + extractive "generator"), so the gate can be
demoed without an LLM or API key. Swap ``answer()`` for your real pipeline: the only
contract with OpenGrade is ``task(item) -> output`` plus ``opengrade.set_retrieval_documents``.

Two env knobs simulate code changes a PR could make:

- ``RAG_TOP_K`` (default 3): how many documents the retriever returns.
- ``RAG_TOKENIZER`` (default ``normalized``): ``raw`` simulates a buggy refactor that
  stops lowercasing / stripping punctuation, so many queries stop matching their document.
"""

from __future__ import annotations

import os
import re
from typing import Any

import opengrade

KB: dict[str, str] = {
    "pto": "Full-time employees receive 20 days of PTO per calendar year.",
    "remote": "The hybrid policy requires at least 3 office days per week.",
    "vpn": "Use the GlobalProtect VPN client for remote access to internal systems.",
    "expenses": "Submit expense reports in Concur within 30 days of the purchase date.",
    "parental": "Parental leave is 16 weeks fully paid for all new parents.",
    "laptop": "Laptops are refreshed every 3 years; request a replacement in ServiceNow.",
    "password": "Passwords must be rotated every 90 days and contain at least 14 characters.",
    "payroll": "Payroll is processed on the last business day of each month.",
    "benefits": "Health insurance enrollment opens every November for the following year.",
    "travel": "Business travel must be booked through Navan at least 14 days in advance.",
}

_STOPWORDS = frozenset(
    "a an the is are do does i my to of for in on how what when where which who should".split()
)


def _tokens(text: str) -> set[str]:
    if os.getenv("RAG_TOKENIZER", "normalized") == "raw":
        words = text.split()  # bug: keeps case and punctuation ("PTO?" != "pto")
    else:
        words = re.findall(r"[a-z0-9]+", text.lower())
    return {w for w in words if w not in _STOPWORDS}


def retrieve(question: str) -> list[dict[str, Any]]:
    top_k = int(os.getenv("RAG_TOP_K", "3"))
    query = _tokens(question)
    scored = []
    for doc_id, text in KB.items():
        overlap = len(query & (_tokens(text) | {doc_id}))
        if overlap:
            scored.append((overlap, doc_id, text))
    scored.sort(key=lambda row: (-row[0], row[1]))
    return [{"id": doc_id, "text": text, "score": s} for s, doc_id, text in scored[:top_k]]


def answer(question: str) -> str:
    docs = retrieve(question)
    opengrade.set_retrieval_documents(docs)
    if not docs:
        return "I don't know."
    return docs[0]["text"]


def task(item: Any) -> str:
    """Entry point for ``opengrade evaluate`` (``evaluate.task: rag_app:task``)."""
    return answer(str(item.input))
