from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
APP_DIR = ROOT / "examples" / "hr_it_assistant"
sys.path.insert(0, str(APP_DIR))

from judge_sanity_lib import (  # noqa: E402
    VARIANTS,
    build_variant_sample,
    build_variant_samples,
    check_thresholds,
    iter_gold_items,
    load_thresholds,
    mean_applicable,
)
from kb import load_knowledge  # noqa: E402


@pytest.fixture(scope="module")
def docs() -> list[dict]:
    return load_knowledge()


def test_iter_gold_has_at_least_twelve(docs: list[dict]) -> None:
    items = iter_gold_items(docs)
    assert len(items) >= 12
    assert all(i["expected_answer"] and i["must_contain"] for i in items)


def test_good_variant_uses_gold_doc_and_answer(docs: list[dict]) -> None:
    item = iter_gold_items(docs)[0]
    sample = build_variant_sample(item, "good", docs=docs)
    assert sample["actual_output"] == item["expected_answer"]
    assert sample["context"]["documents"][0]["id"] == item["doc_id"]
    assert sample["metadata"]["expected_doc_ids"] == [item["doc_id"]]


def test_wrong_fact_replaces_must_contain(docs: list[dict]) -> None:
    item = next(i for i in iter_gold_items(docs) if i["doc_id"] == "pto")
    sample = build_variant_sample(item, "wrong_fact", docs=docs)
    assert "20 days" not in sample["actual_output"]
    assert "5 days" in sample["actual_output"]
    assert sample["context"]["documents"][0]["id"] == "pto"


def test_hallucination_appends_ungrounded_claim(docs: list[dict]) -> None:
    item = iter_gold_items(docs)[0]
    sample = build_variant_sample(item, "hallucination", docs=docs)
    assert item["must_contain"] in sample["actual_output"]
    assert "unlimited free parking" in sample["actual_output"].lower()
    assert sample["context"]["documents"][0]["id"] == item["doc_id"]


def test_bad_retrieval_uses_wrong_doc(docs: list[dict]) -> None:
    item = next(i for i in iter_gold_items(docs) if i["doc_id"] == "pto")
    sample = build_variant_sample(item, "bad_retrieval", docs=docs)
    assert sample["actual_output"] == item["expected_answer"]
    retrieved_id = sample["context"]["documents"][0]["id"]
    assert retrieved_id != "pto"
    assert sample["metadata"]["expected_doc_ids"] == ["pto"]


def test_build_variant_samples_covers_all_variants(docs: list[dict]) -> None:
    for variant in VARIANTS:
        samples = build_variant_samples(variant, docs=docs)
        assert len(samples) == len(iter_gold_items(docs))
        assert all(s["metadata"]["variant"] == variant for s in samples)


def test_load_thresholds_and_check() -> None:
    thresholds = load_thresholds(APP_DIR / "judge_sanity_thresholds.yaml")
    assert "good" in thresholds["variants"]
    ok = check_thresholds(
        {
            "good": {
                "correctness": 0.9,
                "groundedness": 1.0,
                "answer_relevance": 1.0,
                "hit_at_k": 1.0,
                "context_recall": 1.0,
            }
        },
        thresholds,
    )
    assert ok == []
    bad = check_thresholds(
        {"good": {"correctness": 0.1, "hit_at_k": 1.0}},
        thresholds,
    )
    assert any("correctness" in msg for msg in bad)


def test_mean_applicable_skips_none() -> None:
    assert mean_applicable([1.0, None, 0.0]) == pytest.approx(0.5)
    assert mean_applicable([None, None]) is None
