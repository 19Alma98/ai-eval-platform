"""Knowledge base + two retriever architectures for the Nimbus support assistant.

This is plain application code: it knows nothing about OpenGrade. The RAG pipeline in
``rag.py`` is where tracing is added. Two retrievers are provided on purpose so the tour
can compare architectures:

- ``keyword``: counts the question words found in each document. Simple and fast, but
  every word weighs the same, so frequent words ("plan", "file") add noise.
- ``bm25``: the classic BM25 ranking. Rare words weigh more and long documents are
  normalised, which usually ranks the right document higher.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from functools import cache

from nimbus_apps.settings import DATA_DIR

STOPWORDS = frozenset(
    """a an and are at be by can do does for from get how i if in is it my of on or the
    this to what when where which who will with you your me we our long much many""".split()
)


@dataclass(frozen=True)
class Document:
    id: str
    title: str
    text: str


def tokenize(text: str) -> list[str]:
    """Lowercase words without stopwords; a trailing plural "s" is dropped ("links" -> "link")."""
    words = re.findall(r"[a-z0-9]+", text.lower())
    return [w[:-1] if len(w) > 3 and w.endswith("s") else w for w in words if w not in STOPWORDS]


@cache
def load_documents() -> tuple[Document, ...]:
    rows = json.loads((DATA_DIR / "knowledge_base.json").read_text(encoding="utf-8"))
    return tuple(Document(**row) for row in rows)


def keyword_search(question: str, top_k: int) -> list[tuple[Document, float]]:
    query = set(tokenize(question))
    scored = []
    for doc in load_documents():
        overlap = len(query & set(tokenize(doc.title + " " + doc.text)))
        if overlap:
            scored.append((doc, float(overlap)))
    scored.sort(key=lambda pair: -pair[1])
    return scored[:top_k]


def bm25_search(
    question: str, top_k: int, k1: float = 1.2, b: float = 0.75
) -> list[tuple[Document, float]]:
    docs = load_documents()
    tokenized = [tokenize(d.title + " " + d.text) for d in docs]
    avg_len = sum(len(t) for t in tokenized) / len(tokenized)
    doc_freq = Counter(word for tokens in tokenized for word in set(tokens))
    scored = []
    for doc, tokens in zip(docs, tokenized, strict=True):
        tf = Counter(tokens)
        score = 0.0
        for word in set(tokenize(question)):
            if word not in tf:
                continue
            idf = math.log(1 + (len(docs) - doc_freq[word] + 0.5) / (doc_freq[word] + 0.5))
            norm = tf[word] * (k1 + 1) / (tf[word] + k1 * (1 - b + b * len(tokens) / avg_len))
            score += idf * norm
        if score > 0:
            scored.append((doc, round(score, 3)))
    scored.sort(key=lambda pair: -pair[1])
    return scored[:top_k]


RETRIEVERS = {"keyword": keyword_search, "bm25": bm25_search}


def search(question: str, *, strategy: str = "bm25", top_k: int = 3) -> list[dict[str, object]]:
    """Return the ``top_k`` documents as dicts with ``id``, ``text`` and ``score``.

    ``id`` is what OpenGrade compares with the gold ``expected_doc_ids`` (hit@k, recall@k,
    MRR); ``text`` is what LLM judges read (groundedness, context precision).
    """
    try:
        retriever = RETRIEVERS[strategy]
    except KeyError:
        raise ValueError(
            f"unknown retriever {strategy!r}; choose one of {sorted(RETRIEVERS)}"
        ) from None
    return [
        {"id": doc.id, "title": doc.title, "text": doc.text, "score": score}
        for doc, score in retriever(question, top_k)
    ]
