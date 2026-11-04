from __future__ import annotations

from pathlib import Path

from kb import (
    expected_for_question,
    gold_rows_for_api,
    iter_gold,
    load_knowledge,
    retrieve,
)

HERE = Path(__file__).resolve().parent


def test_load_knowledge_has_at_least_twelve_docs() -> None:
    docs = load_knowledge(HERE / "knowledge.json")
    assert len(docs) >= 12
    assert all("id" in d and "body" in d and "gold" in d for d in docs)


def test_every_must_contain_appears_in_body() -> None:
    docs = load_knowledge(HERE / "knowledge.json")
    for doc in docs:
        body_l = doc["body"].lower()
        for g in doc["gold"]:
            assert g["must_contain"].lower() in body_l, (doc["id"], g)


def test_expected_answer_present_and_contains_must_contain() -> None:
    docs = load_knowledge(HERE / "knowledge.json")
    for doc in docs:
        for g in doc["gold"]:
            answer = str(g.get("expected_answer") or "").strip()
            assert answer, (doc["id"], g["question"])
            assert g["must_contain"].lower() in answer.lower(), (doc["id"], g)


def test_retrieve_ranks_pto_question() -> None:
    docs = load_knowledge(HERE / "knowledge.json")
    hits = retrieve(docs, "How many PTO days do full-time employees get?", top_k=2)
    assert hits
    assert hits[0]["id"] == "pto"


def test_iter_gold_and_expected() -> None:
    docs = load_knowledge(HERE / "knowledge.json")
    gold = iter_gold(docs)
    assert len(gold) >= 12
    q, answer, doc_id = gold[0]
    assert doc_id
    assert "20 days" in answer
    assert expected_for_question(docs, q) == answer


def test_gold_rows_for_api_uses_full_expected_answer() -> None:
    rows = gold_rows_for_api()
    assert len(rows) >= 12
    pto = next(r for r in rows if "PTO days" in r["question"])
    assert pto["expected_output"] == "Full-time employees receive 20 days of PTO per calendar year."
    assert pto["must_contain"] == ["20 days"]
    assert pto["expected_doc_ids"] == ["pto"]
