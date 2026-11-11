"""Register the gold test sets on the platform under a readable name.

``og.evaluate(dataset="data/gold_rag.jsonl", ...)`` would also work (the file is
uploaded and named after a hash of its rows). Registering it once under a name such as
``nimbus-rag-gold-v1`` makes it easy to find in the UI (Datasets) and to reuse from any
script, notebook or CI job: ``og.evaluate(dataset="nimbus-rag-gold-v1", ...)``.

Change the questions? Bump the version in the name: experiments are only comparable when
they ran on the same test set.
"""

from __future__ import annotations

import json
from typing import Any

from nimbus_apps.settings import DATA_DIR

RAG_GOLD = "nimbus-rag-gold-v1"
RAG_CHAT_GOLD = "nimbus-rag-chat-gold-v1"
TICKETS_GOLD = "nimbus-tickets-gold-v1"

_FILES = {
    RAG_GOLD: ("gold_rag.jsonl", "rag_qa"),
    RAG_CHAT_GOLD: ("gold_rag_chat.jsonl", "rag_chat"),
    TICKETS_GOLD: ("gold_tickets.jsonl", "classification"),
}


def read_jsonl(filename: str) -> list[dict[str, Any]]:
    lines = (DATA_DIR / filename).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def ensure_dataset(name: str) -> str:
    """Return the dataset id, creating the dataset from ``data/`` the first time."""
    from nimbus_apps.telemetry import og

    client = og.client
    existing = [d for d in client.datasets.list() if d.name == name]
    if existing:
        return max(existing, key=lambda d: d.version).id
    filename, task_type = _FILES[name]
    created = client.datasets.create_with_items(
        name=name, task_type=task_type, items=read_jsonl(filename)
    )
    return created.id
