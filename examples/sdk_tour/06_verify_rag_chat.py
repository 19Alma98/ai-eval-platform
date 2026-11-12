"""06 - Verify multi-turn RAG (rag_chat) and the conversational judges.

Use case: "My assistant is a chat. Does it stay consistent, rewrite the query
faithfully, and resolve the user's need?"

The gold set is data/gold_rag_chat.jsonl (two follow-up turns). Each row has:

  input.history     prior user/assistant turns
  input.question    the last user question (what the experiment scores)
  expected_output   reference answer for that last turn
  metadata          expected_doc_ids / must_contain for retrieval + facts

What this script shows:

  1. Register the chat gold set (task_type rag_chat).
  2. Run the chat pipeline with opengrade.chat_input + set_search_query.
  3. Score with deterministic metrics always; always request the three
     conversational judges (query_rewrite_faithfulness, conversation_consistency,
     resolution) so you can verify them when the platform has LLM_MODEL set.
  4. Print per-metric results, including ERROR if judges could not run.

Offline (default fake model):

  uv run python 06_verify_rag_chat.py

Real generation via Ollama (OpenAI-compatible API on :11434):

  uv sync --extra llm
  ollama pull gemma4:e2b
  TOUR_MODEL=gemma4:e2b uv run python 06_verify_rag_chat.py

Then: UI -> Experiments (and Datasets for the chat-shaped items).
"""

from __future__ import annotations

import sys
from collections import defaultdict
from typing import Any

import opengrade

from nimbus_apps import settings
from nimbus_apps.console import note, step, title
from nimbus_apps.datasets import RAG_CHAT_GOLD, ensure_dataset
from nimbus_apps.llm import is_fake
from nimbus_apps.rag import DEFAULT_CONFIG, answer_chat
from nimbus_apps.telemetry import og

CONVERSATION_JUDGES = (
    "query_rewrite_faithfulness",
    "conversation_consistency",
    "resolution",
)

GATE = {
    "hit_at_k": 0.90,
    "must_contain": 0.90,
}


def task(item: Any) -> str:
    turn = opengrade.chat_input(item)
    history = [t.model_dump() for t in turn.history]
    return answer_chat(history, turn.question, DEFAULT_CONFIG)


def _question_preview(raw_input: Any) -> str:
    if isinstance(raw_input, dict):
        question = raw_input.get("question")
        if isinstance(question, str) and question.strip():
            return question
    return str(raw_input)


def print_failures(result: opengrade.ExperimentResult) -> None:
    problems: dict[str, list[str]] = defaultdict(list)
    for item_id, metrics in result.by_item.items():
        for name, r in metrics.items():
            if r.label in ("FAIL", "ERROR"):
                problems[item_id].append(f"{name}: {r.explanation}")

    by_id = {run.item.id: run for run in result.items}
    if not problems:
        print("  every item passed every metric (or was skipped)")
        return
    for item_id, reasons in problems.items():
        run = by_id[item_id]
        print(f"  x {_question_preview(run.item.input)}")
        print(f"      answer:   {run.output}")
        print(f"      expected: {run.item.expected_output}")
        for reason in reasons:
            print(f"      - {reason}")


def _judge_labels(result: opengrade.ExperimentResult) -> dict[str, list[str]]:
    """Map judge kind -> labels seen across items (PASS/FAIL/SKIPPED/ERROR/...)."""
    out: dict[str, list[str]] = {kind: [] for kind in CONVERSATION_JUDGES}
    for name, results in result.by_metric.items():
        kind = next((k for k in CONVERSATION_JUDGES if k == name or k in name), None)
        if kind is None:
            continue
        for r in results:
            out[kind].append(r.label or "UNKNOWN")
    return out


def main() -> None:
    title("OpenGrade SDK tour - 06 Verify multi-turn RAG chat")

    step(0, "Connect")
    if og.set_project(settings.PROJECT) is None:
        sys.exit(f"OpenGrade is not reachable at {settings.TRACKING_URI}: start it first.")
    model = DEFAULT_CONFIG.model
    print(f"  generation model: {model}")
    if is_fake(model):
        note(
            f"Using offline {model}. For a real Ollama run: "
            f"`uv sync --extra llm && TOUR_MODEL=<ollama-tag> uv run python 06_verify_rag_chat.py` "
            f"(endpoint {settings.LLM_BASE_URL})."
        )
    else:
        print(f"  LLM endpoint:    {settings.LLM_BASE_URL}")
        note("Real model: answer_chat sends history + retrieved docs to the OpenAI-compatible API.")
    og.init_tracing(service_name="nimbus-support-chat-eval", instrument="auto")
    client = og.client

    step(1, "Register the chat gold set")
    dataset_id = ensure_dataset(RAG_CHAT_GOLD)
    items = client.datasets.get(dataset_id).items
    print(f"  dataset '{RAG_CHAT_GOLD}': {len(items)} chat items (id {dataset_id})")
    note("UI -> Datasets: each row shows history + the last question (task_type rag_chat).")

    step(2, "Run the chat pipeline + conversation judges")
    metrics: list[Any] = [
        "hit_at_k",
        "must_contain",
        *CONVERSATION_JUDGES,
    ]
    result = og.evaluate(
        dataset=RAG_CHAT_GOLD,
        task=task,
        metrics=metrics,
        name=f"rag_chat {DEFAULT_CONFIG.model} {DEFAULT_CONFIG.retriever}",
        params={**vars(DEFAULT_CONFIG)},
        max_concurrency=2,
    )
    print(result.summary())
    note(
        """query_rewrite_faithfulness needs set_search_query on the trace.
        conversation_consistency / resolution need multi-turn history + the answer.
        Without a judge model on the server (LLM_MODEL + API key), those three show
        as ERROR / 'could not run' — deterministic metrics still score."""
    )

    step(3, "Conversational judge status")
    labels = _judge_labels(result)
    for kind in CONVERSATION_JUDGES:
        seen = labels.get(kind) or []
        if not seen:
            # Fallback: look up by metric mean keys / evaluator names in summary.
            value = result.metrics.get(kind)
            print(f"  {kind:<32} metric={value!r}  (no per-item labels found)")
            continue
        errors = sum(1 for lab in seen if lab == "ERROR")
        skipped = sum(1 for lab in seen if lab == "SKIPPED")
        print(
            f"  {kind:<32} labels={seen}"
            + ("  <- configure server LLM_MODEL to score" if errors else "")
            + ("  (skipped: missing history/search_query)" if skipped and not errors else "")
        )

    step(4, "Which items failed")
    print_failures(result)

    step(5, "Quality gate (deterministic only)")
    passed = True
    for metric_name, minimum in GATE.items():
        value = result.metrics.get(metric_name)
        ok = value is not None and value >= minimum
        passed &= ok
        shown = "n/a" if value is None else f"{value:.2f}"
        print(f"  {'PASS' if ok else 'FAIL'}  {metric_name:<24} {shown:>5}  (min {minimum})")
    if not passed:
        print("  -> gate failed")
    else:
        print("  -> gate passed")

    print(f"\nOpen {result.url}")
    og.flush()
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
