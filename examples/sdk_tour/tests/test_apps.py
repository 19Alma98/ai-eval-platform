"""Offline checks of the demo apps and metrics (no platform needed): uv run pytest."""

from __future__ import annotations

import opengrade
import pytest

from nimbus_apps.classifier import classify_ticket, redact_pii
from nimbus_apps.datasets import read_jsonl
from nimbus_apps.llm import REFUSAL, _fake_answer
from nimbus_apps.quality import cites_retrieved_source, refusal_is_correct
from nimbus_apps.retrieval import search

RAG_GOLD = read_jsonl("gold_rag.jsonl")
TICKETS = read_jsonl("gold_tickets.jsonl")


@pytest.mark.parametrize("row", RAG_GOLD, ids=lambda r: r["input"][:40])
def test_bm25_finds_a_gold_document(row: dict) -> None:
    ids = {d["id"] for d in search(row["input"], strategy="bm25", top_k=3)}
    assert ids & set(row["metadata"]["expected_doc_ids"])


def test_fake_models_differ_on_out_of_scope_questions() -> None:
    docs = search("Who is the CEO of Nimbus?", top_k=3)
    assert _fake_answer("fake-large", "Who is the CEO of Nimbus?", docs) == REFUSAL
    assert _fake_answer("fake-small", "Who is the CEO of Nimbus?", docs) != REFUSAL


def test_classifier_v2_beats_v1() -> None:
    def accuracy(model: str) -> float:
        hits = [classify_ticket(t["input"], model=model) == t["expected_output"] for t in TICKETS]
        return sum(hits) / len(hits)

    assert accuracy("rules-v2") > accuracy("rules-v1")


def test_pii_is_masked() -> None:
    clean, masked = redact_pii("mail bob@example.com, card 4111 1111 1111 1111")
    assert masked == 2 and "bob@" not in clean and "4111" not in clean


def test_invented_citation_fails() -> None:
    sample = opengrade.Sample(output="20 days [pto]", documents=[{"id": "plans", "text": "..."}])
    assert cites_retrieved_source.fn(sample).value == 0.0


def test_refusal_outcomes() -> None:
    over = opengrade.Sample(output=REFUSAL, metadata={"answerable": True})
    missed = opengrade.Sample(output="Sure!", metadata={"answerable": False})
    assert refusal_is_correct.fn(over).explanation == "over_refusal"
    assert refusal_is_correct.fn(missed).explanation == "missed_refusal"
