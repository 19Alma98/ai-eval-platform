"""02 - Verify that the RAG answers correctly, against a gold test set.

Use case: "I want to check that my RAG gives the right answers, before I ship it."

Tracing (script 01) tells you *what happened*. To know whether it was *right* you need
a test set with the expected results, the "gold" set: data/gold_rag.jsonl. Each row has:

  input             the customer question
  expected_output   a reference answer written by a person
  metadata.expected_doc_ids   documents that contain the answer   -> retrieval metrics
  metadata.must_contain       facts the answer must state          -> must_contain
  metadata.answerable         false = the docs do not cover it     -> refusal metric
  metadata.category           billing / files / security / ...     -> per-group scores

What this script shows, step by step:

  1. Register the gold set on the platform (Datasets in the UI).
  2. Test the retriever alone: is the right document found? (hit@k, recall@k, MRR)
  3. Test the whole pipeline: built-in metrics + your own Python metrics, per category,
     compared with the last accepted version (the baseline).
  4. Read the failures item by item, programmatically.
  5. Apply a quality gate (minimum scores) and promote the run as the new baseline.

Run:  uv run python 02_verify_rag.py
      TOUR_MODEL=fake-small uv run python 02_verify_rag.py   # a worse model: gate fails
Then: UI -> Experiments.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from typing import Any

import opengrade

from nimbus_apps import settings
from nimbus_apps.console import note, step, title
from nimbus_apps.datasets import RAG_GOLD, ensure_dataset
from nimbus_apps.quality import answer_is_concise, cites_retrieved_source, refusal_is_correct
from nimbus_apps.rag import DEFAULT_CONFIG, answer_question
from nimbus_apps.retrieval import search

# Your own Python metrics (nimbus_apps/quality.py), used next to the built-in ones.
LOCAL_METRICS = [cites_retrieved_source, refusal_is_correct, answer_is_concise]

BASELINE_ALIAS = "rag-main"  # the version currently accepted ("what is in production")

# Quality gate: the minimum mean score of each metric for a version to be accepted.
GATE = {
    "hit_at_k": 0.90,  # the right document is in the top k for 90% of the questions
    "must_contain": 0.75,  # 3 answers out of 4 state the expected facts
    "refusal_is_correct": 0.90,  # refuses when (and only when) it should
    "cites_retrieved_source": 0.90,  # no invented citations
}


def task(item: Any) -> str:
    """What the experiment runs for each gold row: your app, unchanged.

    ``item.input`` is the question. Documents recorded by ``set_retrieval_documents``
    inside ``answer_question`` are picked up automatically for retrieval metrics.
    """
    return answer_question(item.input, DEFAULT_CONFIG)


def print_failures(result: opengrade.ExperimentResult) -> None:
    """Item-level view: which question failed which metric, and why.

    ``result.evaluation.runs`` holds one run per metric (built-in and yours, since local
    metric scores are submitted to the platform too), each with one result per item.
    """
    names = {e.evaluator_id: e.evaluator_name for e in result.server_summary.evaluators}
    problems: dict[str, list[str]] = defaultdict(list)
    for run in result.evaluation.runs if result.evaluation else []:
        for r in run.results:
            if r.label in ("FAIL", "ERROR"):
                problems[r.dataset_item_id].append(
                    f"{names.get(run.evaluator_id)}: {r.explanation}"
                )

    by_id = {run.item.id: run for run in result.items}
    if not problems:
        print("  every item passed every metric")
    for item_id, reasons in problems.items():
        run = by_id[item_id]
        print(f"  x {run.item.input}")
        print(f"      answer:   {run.output}")
        print(f"      expected: {run.item.expected_output}")
        for reason in reasons:
            print(f"      - {reason}")


def main() -> None:
    title("OpenGrade SDK tour - 02 Verify the RAG answers")

    step(0, "Connect")
    opengrade.set_tracking_uri(settings.TRACKING_URI)
    if opengrade.set_project(settings.PROJECT) is None:
        sys.exit(f"OpenGrade is not reachable at {settings.TRACKING_URI}: start it first.")
    # Tracing on during experiments: each item gets its trace (tokens, cost, spans).
    opengrade.init(service_name="nimbus-support-eval", instrument="auto")
    client = opengrade.get_client()

    step(1, "Register the gold test set")
    dataset_id = ensure_dataset(RAG_GOLD)
    items = client.datasets.get(dataset_id).items
    print(f"  dataset '{RAG_GOLD}': {len(items)} questions (id {dataset_id})")
    note("UI -> Datasets: every question with its reference answer and metadata.")

    step(2, "Retrieval only: does the retriever find the right documents?")
    # No answer is generated: cheap enough to run on every change to chunking/embeddings.
    retrieval = opengrade.evaluate_retrieval(
        dataset=RAG_GOLD,
        retriever=lambda query: search(
            query, strategy=DEFAULT_CONFIG.retriever, top_k=DEFAULT_CONFIG.top_k
        ),
        k=DEFAULT_CONFIG.top_k,
        name=f"retrieval {DEFAULT_CONFIG.retriever} k={DEFAULT_CONFIG.top_k}",
    )
    print(retrieval.summary())
    note(
        """hit_at_k = share of questions with at least one gold document in the top k.
        recall_at_k = share of the gold documents found (matters for questions that need
        two documents). mrr = how high the first gold document ranks (1.0 = always first).
        Questions with no gold documents (out of scope) are skipped."""
    )

    step(3, "End-to-end: answers scored by built-in and custom metrics")
    aliases = {a.name for a in client.experiments.list_aliases()}
    baseline = f"alias:{BASELINE_ALIAS}" if BASELINE_ALIAS in aliases else None
    metrics: list[Any] = [
        "hit_at_k",  # built-in, deterministic: gold document retrieved?
        "must_contain",  # built-in, deterministic: expected facts in the answer?
        "latency",  # built-in: end-to-end latency of the traced call
        *LOCAL_METRICS,  # yours: cites_retrieved_source, refusal_is_correct, ...
    ]
    if settings.USE_LLM_JUDGES:
        # Built-in LLM judges: need a judge model configured on the platform.
        metrics += ["groundedness", "correctness", "answer_relevance", "citation_accuracy"]
    result = opengrade.evaluate(
        dataset=RAG_GOLD,
        task=task,
        metrics=metrics,
        name=f"rag {DEFAULT_CONFIG.model} {DEFAULT_CONFIG.retriever} k={DEFAULT_CONFIG.top_k}",
        params={**vars(DEFAULT_CONFIG)},  # stored with the run: what exactly was tested
        baseline=baseline,  # compare with the accepted version, when there is one
        group_by="category",  # also score each category separately
        max_concurrency=4,
    )
    print(result.summary())
    note(
        """mean = average score, pass_rate = share of items at or above the metric
        threshold. 'by category' shows where the assistant is weak even when the global
        mean looks fine. With a baseline, the last column is the change vs that run."""
    )

    step(4, "Which questions failed, and why")
    print_failures(result)

    step(5, "Quality gate + promotion")
    passed = True
    for metric_name, minimum in GATE.items():
        value = result.metrics.get(metric_name)
        ok = value is not None and value >= minimum
        passed &= ok
        shown = "n/a" if value is None else f"{value:.2f}"
        print(f"  {'PASS' if ok else 'FAIL'}  {metric_name:<24} {shown:>5}  (min {minimum})")
    if passed:
        client.experiments.set_alias(BASELINE_ALIAS, result.id, note="gate passed")
        print(f"  -> gate passed: this run is now the '{BASELINE_ALIAS}' baseline")
    else:
        print(f"  -> gate failed: '{BASELINE_ALIAS}' is not moved")
    note(
        """In CI you get the same thing (plus statistical regression checks and Markdown/JUnit
        reports) with the `opengrade evaluate` command: see examples/ci_regression_gate."""
    )
    opengrade.flush()
    print(f"\nOpen {result.url}")
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
