"""RAG pipeline with a real LLM, used by the LLM regression-gate example.

Environment:

- ``RAG_LLM_BASE_URL`` (default ``http://localhost:11434/v1``, Ollama)
- ``RAG_LLM_MODEL`` (default ``gemma4:e2b``)
- ``RAG_LLM_API_KEY`` (default ``ollama``; set from a CI secret for a cloud model)
- ``RAG_TEMPERATURE`` (default ``0.3``)
- ``RAG_PROMPT`` (default ``v1``): ``no_context`` simulates a refactor that stopped
  passing the retrieved documents to the model, so it answers from memory.
"""

from __future__ import annotations

import os
import re
from typing import Any

import opengrade
from openai import OpenAI

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
    "mfa": "Multi-factor authentication with the Okta Verify app is mandatory for all accounts.",
    "incident": "Report a security incident within 1 hour to security@acme.example.",
}

_STOPWORDS = frozenset(
    ["a", "an", "the", "is", "are", "do", "does", "i", "my", "to", "of", "for", "in", "on", "how", "what", "when", "where", "which", "who", "should"]
)

SYSTEM_PROMPT = (
    "You are the internal HR / IT assistant. Answer in one or two sentences using only "
    "the context. Keep numbers, names and tools exactly as written in the context. "
    "If the context does not contain the answer, say you don't know."
)

_client: OpenAI | None = None


def _llm() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            base_url=os.getenv("RAG_LLM_BASE_URL", "http://localhost:11434/v1"),
            api_key=os.getenv("RAG_LLM_API_KEY", "ollama"),
            timeout=60.0,
        )
    return _client


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _STOPWORDS}


def retrieve(question: str, top_k: int = 3) -> list[dict[str, Any]]:
    query = _tokens(question)
    scored = []
    for doc_id, text in KB.items():
        overlap = len(query & (_tokens(text) | {doc_id}))
        if overlap:
            scored.append((overlap, doc_id, text))
    scored.sort(key=lambda row: (-row[0], row[1]))
    return [{"id": doc_id, "text": text, "score": s} for s, doc_id, text in scored[:top_k]]


def generate(question: str, docs: list[dict[str, Any]]) -> str:
    if os.getenv("RAG_PROMPT", "v1") == "no_context":
        user = question
    else:
        context = "\n".join(f"[{d['id']}] {d['text']}" for d in docs) or "(no documents)"
        user = f"Context:\n{context}\n\nQuestion: {question}"
    response = _llm().chat.completions.create(
        model=os.getenv("RAG_LLM_MODEL", "gemma4:e2b"),
        temperature=float(os.getenv("RAG_TEMPERATURE", "0.3")),
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
    )
    return (response.choices[0].message.content or "").strip()


def task(item: Any) -> str:
    """Entry point for ``opengrade evaluate`` (``evaluate.task: rag_app:task``)."""
    question = str(item.input)
    docs = retrieve(question)
    opengrade.set_retrieval_documents(docs)
    return generate(question, docs)
