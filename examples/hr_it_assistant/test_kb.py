from __future__ import annotations

from pathlib import Path

from kb import expected_for_question, iter_gold, load_knowledge, retrieve

HERE = Path(__file__).resolve().parent


def test_load_knowledge_has_at_least_eight_docs() -> None:
    docs = load_knowledge(HERE / "knowledge.json")
    assert len(docs) >= 8
    assert all("id" in d and "body" in d and "gold" in d for d in docs)


def test_every_must_contain_appears_in_body() -> None:
    docs = load_knowledge(HERE / "knowledge.json")
    for doc in docs:
        body_l = doc["body"].lower()
        for g in doc["gold"]:
            assert g["must_contain"].lower() in body_l, (doc["id"], g)


def test_retrieve_ranks_pto_question() -> None:
    docs = load_knowledge(HERE / "knowledge.json")
    hits = retrieve(docs, "How many PTO days do full-time employees get?", top_k=2)
    assert hits
    assert hits[0]["id"] == "pto"


def test_iter_gold_and_expected() -> None:
    docs = load_knowledge(HERE / "knowledge.json")
    gold = iter_gold(docs)
    assert len(gold) >= 8
    q, must = gold[0]
    assert expected_for_question(docs, q) == must
