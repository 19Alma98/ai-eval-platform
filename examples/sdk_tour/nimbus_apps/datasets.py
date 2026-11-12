"""Register the gold test sets on the platform under a stable name.

``og.evaluate(dataset="data/gold_rag.jsonl", ...)`` would also work (the file is
uploaded and named after a hash of its rows). Registering it once under a readable
name such as ``nimbus-rag-gold`` makes it easy to find in the UI (Datasets) and to
reuse from any script, notebook or CI job: ``og.evaluate(dataset="nimbus-rag-gold", ...)``.

When the JSONL changes, ``ensure_dataset`` creates a new platform ``version`` under the
same name (content hash in ``description``). Experiments stay comparable only when they
share the same dataset version.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from nimbus_apps.settings import DATA_DIR

RAG_GOLD = "nimbus-rag-gold"
RAG_CHAT_GOLD = "nimbus-rag-chat-gold"
TICKETS_GOLD = "nimbus-tickets-gold"

_FILES = {
    RAG_GOLD: ("gold_rag.jsonl", "rag_qa"),
    RAG_CHAT_GOLD: ("gold_rag_chat.jsonl", "rag_chat"),
    TICKETS_GOLD: ("gold_tickets.jsonl", "classification"),
}

_HASH_PREFIX = "content_hash="


def read_jsonl(filename: str) -> list[dict[str, Any]]:
    lines = (DATA_DIR / filename).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def items_digest(items: list[dict[str, Any]]) -> str:
    """Stable SHA-256 of the gold rows (order-preserving, key-sorted JSON)."""
    raw = json.dumps(items, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _hash_from_description(description: str | None) -> str | None:
    if not description or not description.startswith(_HASH_PREFIX):
        return None
    value = description.removeprefix(_HASH_PREFIX).strip()
    return value or None


def ensure_dataset(name: str) -> str:
    """Return the dataset id for ``name``, creating a new version when the JSONL changed."""
    from nimbus_apps.telemetry import og

    if name not in _FILES:
        raise KeyError(f"unknown gold dataset {name!r}; expected one of {sorted(_FILES)}")

    filename, task_type = _FILES[name]
    items = read_jsonl(filename)
    digest = items_digest(items)
    description = f"{_HASH_PREFIX}{digest}"

    client = og.client
    existing = client.datasets.list(name=name)
    matching = [d for d in existing if _hash_from_description(d.description) == digest]
    if matching:
        return max(matching, key=lambda d: d.version).id

    next_version = max((d.version for d in existing), default=0) + 1
    created = client.datasets.create_with_items(
        name=name,
        task_type=task_type,
        items=items,
        version=next_version,
        description=description,
    )
    return created.id
