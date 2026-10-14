"""Pure helpers for the offline judge sanity suite (no live LLM)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from kb import load_knowledge

HERE = Path(__file__).resolve().parent
DEFAULT_THRESHOLDS = HERE / "judge_sanity_thresholds.yaml"

VARIANTS = ("good", "wrong_fact", "hallucination", "bad_retrieval", "refusal")
METRIC_KINDS = (
    "correctness",
    "groundedness",
    "answer_relevance",
    "hit_at_k",
    "context_recall",
)

# Deterministic inverted facts for wrong_fact (must_contain -> replacement).
_WRONG_FACT: dict[str, str] = {
    "20 days": "5 days",
    "3 office days": "1 office day",
    "GlobalProtect": "OpenVPN",
    "Concur": "Expensify",
    "ServiceNow": "Jira Service Desk",
    "aka.ms/sspr": "password.acme.example",
    "security@acme.example": "front-desk@acme.example",
    "Northwind Health": "Contoso Care",
    "16 weeks": "2 weeks",
    "Contoso Travel": "Expedia",
    "acme-corp": "acme-chat",
    "Workday": "BambooHR",
}

_HALLUCINATION_TAIL = (
    " Employees also receive an unlimited free parking stipend downtown."
)

REFUSAL_ANSWER = (
    "I don't know. I don't have enough information in the available policy "
    "to answer that."
)


def load_thresholds(path: Path | None = None) -> dict[str, Any]:
    target = path or DEFAULT_THRESHOLDS
    raw = yaml.safe_load(target.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or "variants" not in raw:
        raise ValueError(f"thresholds file must have a top-level 'variants' map: {target}")
    return raw


def _doc_payload(doc: dict[str, Any]) -> dict[str, str]:
    return {
        "id": str(doc["id"]),
        "title": str(doc.get("title") or doc["id"]),
        "text": str(doc["body"]),
    }


def _wrong_answer(expected: str, must_contain: str) -> str:
    replacement = _WRONG_FACT.get(must_contain)
    if replacement is None:
        replacement = f"NOT-{must_contain}"
    if must_contain in expected:
        return expected.replace(must_contain, replacement, 1)
    # Case-insensitive fallback
    lower = expected.lower()
    idx = lower.find(must_contain.lower())
    if idx >= 0:
        return expected[:idx] + replacement + expected[idx + len(must_contain) :]
    return f"{replacement}. (incorrect policy summary)"


def _other_doc(docs: list[dict[str, Any]], gold_doc_id: str) -> dict[str, Any]:
    for doc in docs:
        if str(doc["id"]) != gold_doc_id:
            return doc
    raise RuntimeError("need at least two docs for bad_retrieval variant")


def iter_gold_items(
    docs: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    knowledge = docs if docs is not None else load_knowledge()
    items: list[dict[str, Any]] = []
    for doc in knowledge:
        doc_id = str(doc["id"])
        for g in doc.get("gold") or []:
            items.append(
                {
                    "question": str(g["question"]),
                    "expected_answer": str(g["expected_answer"]).strip(),
                    "must_contain": str(g["must_contain"]),
                    "doc_id": doc_id,
                    "doc": doc,
                }
            )
    return items


def build_variant_sample(
    item: dict[str, Any],
    variant: str,
    *,
    docs: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a dict matching EvaluationSample fields for one gold item + variant."""
    if variant not in VARIANTS:
        raise ValueError(f"unknown variant {variant!r}; expected one of {VARIANTS}")

    question = item["question"]
    expected = item["expected_answer"]
    must = item["must_contain"]
    gold_doc = item["doc"]
    gold_id = item["doc_id"]

    if variant == "good":
        actual = expected
        documents = [_doc_payload(gold_doc)]
    elif variant == "wrong_fact":
        actual = _wrong_answer(expected, must)
        documents = [_doc_payload(gold_doc)]
    elif variant == "hallucination":
        actual = expected + _HALLUCINATION_TAIL
        documents = [_doc_payload(gold_doc)]
    elif variant == "refusal":
        actual = REFUSAL_ANSWER
        documents = [_doc_payload(gold_doc)]
    else:  # bad_retrieval
        actual = expected
        documents = [_doc_payload(_other_doc(docs, gold_id))]

    return {
        "input": question,
        "expected_output": expected,
        "actual_output": actual,
        "context": {"documents": documents},
        "metadata": {
            "expected_doc_ids": [gold_id],
            "must_contain": [must],
            "variant": variant,
            "gold_doc_id": gold_id,
        },
    }


def build_variant_samples(
    variant: str,
    *,
    docs: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    knowledge = docs if docs is not None else load_knowledge()
    return [
        build_variant_sample(item, variant, docs=knowledge)
        for item in iter_gold_items(knowledge)
    ]


def mean_applicable(scores: list[float | None]) -> float | None:
    values = [s for s in scores if s is not None]
    if not values:
        return None
    return sum(values) / len(values)


def check_thresholds(
    aggregates: dict[str, dict[str, float | None]],
    thresholds: dict[str, Any],
) -> list[str]:
    """Return human-readable failure messages (empty list = pass)."""
    failures: list[str] = []
    variants_cfg = thresholds.get("variants") or {}
    for variant, metrics in aggregates.items():
        cfg = variants_cfg.get(variant) or {}
        for metric, value in metrics.items():
            rules = cfg.get(metric) or {}
            if not rules:
                continue
            if rules.get("null") is True:
                if value is not None:
                    failures.append(
                        f"{variant}.{metric}: expected null aggregate, got {value:.3f}"
                    )
                continue
            if value is None:
                failures.append(f"{variant}.{metric}: no applicable scores")
                continue
            floor = rules.get("min")
            ceil = rules.get("max")
            if floor is not None and value < float(floor):
                failures.append(
                    f"{variant}.{metric}: {value:.3f} < min {float(floor):.3f}"
                )
            if ceil is not None and value > float(ceil):
                failures.append(
                    f"{variant}.{metric}: {value:.3f} > max {float(ceil):.3f}"
                )
    return failures
