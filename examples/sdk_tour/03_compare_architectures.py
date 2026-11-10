"""03 - Compare architectures and models: which configuration is best?

Use case: "I want to test which RAG architecture / which model works best."

Rule number one of a fair comparison: same test set, same metrics, change ONE thing at a
time (or a grid of things), and keep every run. ``og.sweep`` does exactly that:
one experiment per configuration, all on the same gold set, ranked in a leaderboard.

What this script shows, step by step:

  1. Retrieval architectures (retriever x top_k), retrieval only: fast and cheap, no LLM.
  2. Full pipeline (model x retriever): answer quality vs latency, best configuration.
  3. Not only RAG: two versions of the ticket classifier, the new one compared with the
     current one (baseline), with the built-in ``exact_match`` metric.

Run:  uv run python 03_compare_architectures.py
      TOUR_COMPARE_MODELS=fake-large,gemma4:e2b,llama3.2 uv run python 03_compare_architectures.py
Then: UI -> Experiments -> Compare (the link printed at the end of each sweep).
"""

from __future__ import annotations

import sys
from typing import Any

import opengrade
from opengrade import Opengrade, Settings

from nimbus_apps import settings
from nimbus_apps.classifier import classify_ticket
from nimbus_apps.console import note, step, title
from nimbus_apps.datasets import RAG_GOLD, TICKETS_GOLD, ensure_dataset
from nimbus_apps.quality import cites_retrieved_source, refusal_is_correct
from nimbus_apps.rag import DEFAULT_CONFIG, answer_question
from nimbus_apps.retrieval import search

# ---------------------------------------------------------------------------------------
# Tasks: your code, parametrised. A sweep calls them with each configuration's params.
# ---------------------------------------------------------------------------------------


def retrieve_only(item: Any, params: dict[str, Any]) -> list[dict[str, Any]]:
    """Retriever under test: returns the ranked documents, nothing is generated."""
    return search(item.input, strategy=params["retriever"], top_k=params["top_k"])


def full_pipeline(item: Any, params: dict[str, Any]) -> str:
    """The whole RAG with this configuration (unknown keys are ignored)."""
    return answer_question(item.input, DEFAULT_CONFIG.with_params(params))


# ---------------------------------------------------------------------------------------


def main() -> None:
    title("OpenGrade SDK tour - 03 Compare architectures and models")

    step(0, "Connect")
    og = Opengrade(Settings(tracking_uri=settings.TRACKING_URI, project_slug=settings.PROJECT))
    with og.activate():
        if og.set_project(settings.PROJECT) is None:
            sys.exit(f"OpenGrade is not reachable at {settings.TRACKING_URI}: start it first.")
        og.init_tracing(service_name="nimbus-support-eval", instrument="auto")
        ensure_dataset(RAG_GOLD)
        ensure_dataset(TICKETS_GOLD)

        step(1, "Retrieval architectures: retriever x top_k (no LLM)")
        retrieval = og.sweep(
            name="retrieval-architecture",
            dataset=RAG_GOLD,
            retriever=retrieve_only,  # retrieval-only sweep: hit@k, recall@k, MRR
            grid={"retriever": ["keyword", "bm25"], "top_k": [1, 2, 3]},  # 2 x 3 = 6 runs
            k=3,  # metrics look at the first 3 documents
        )
        print(retrieval.summary("recall_at_k"))
        note(
            """Every row is a normal experiment named 'retrieval-architecture [retriever=..,
            top_k=..]'. top_k=1 cannot find both documents of the two-document questions:
            recall drops. With the same top_k, compare keyword and bm25 on mrr: how often
            the right document comes first."""
        )

        step(2, "Full pipeline: model x retriever")
        metrics: list[Any] = ["hit_at_k", "must_contain", cites_retrieved_source, refusal_is_correct]
        if settings.USE_LLM_JUDGES:
            metrics += ["groundedness", "correctness"]
        pipeline = og.sweep(
            name="rag-architecture",
            dataset=RAG_GOLD,
            task=full_pipeline,
            grid={"model": settings.COMPARE_MODELS, "retriever": ["keyword", "bm25"]},
            params={"top_k": 3, "prompt": "v2"},  # fixed for every configuration, stored too
            metrics=metrics,
            max_concurrency=4,
        )
        print(pipeline.summary("must_contain"))

        best = pipeline.best("must_contain")
        fastest = pipeline.best("opengrade.latency_p95_ms")  # latency: lower is better
        if best and best.result:
            print(f"\n  best answers : {best.label}  must_contain={best.value('must_contain'):.2f}")
        if fastest and fastest.result:
            p95 = fastest.value("opengrade.latency_p95_ms") or 0.0
            print(f"  fastest      : {fastest.label}  p95={p95:.0f} ms")
        note(
            """Pick with numbers, not impressions: quality first, then latency/cost. The
            best configuration is often a trade-off; the Compare view plots any two metrics
            against each other (e.g. must_contain vs latency p95). For a DataFrame:
            pandas.DataFrame(pipeline.to_records())."""
        )

        step(3, "Not only RAG: ticket classifier v1 vs v2")
        baseline_run = og.evaluate(
            name="ticket-classifier rules-v1",
            dataset=TICKETS_GOLD,
            task_type="classification",
            task=lambda item: classify_ticket(item.input, model="rules-v1"),
            metrics=["exact_match"],  # predicted label == expected label
            params={"classifier": "rules-v1"},
        )
        candidate = og.evaluate(
            name="ticket-classifier rules-v2",
            dataset=TICKETS_GOLD,
            task_type="classification",
            task=lambda item: classify_ticket(item.input, model="rules-v2"),
            metrics=["exact_match"],
            params={"classifier": "rules-v2"},
            baseline=baseline_run,  # compare with v1: the delta column below
        )
        print(candidate.summary())
        note(
            """Same pattern for any input -> output app: a gold set, a task, metrics. The
            'vs baseline' column says whether the change is a real improvement or noise
            (paired bootstrap over the same items)."""
        )

        print(f"\nCompare the RAG configurations side by side: {pipeline.url}")
    og.flush()


if __name__ == "__main__":
    main()
