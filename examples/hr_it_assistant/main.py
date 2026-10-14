"""Acme People Ops Assistant — FAQ RAG demo via opengrade SDK + Ollama."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from typing import Any

from kb import expected_for_question, gold_rows_for_api, iter_gold, load_knowledge, retrieve
from openai import OpenAI

import opengrade

logger = logging.getLogger(__name__)


def question_from_item_input(raw: Any) -> str:
    if isinstance(raw, str) and raw.strip():
        return raw
    if isinstance(raw, dict):
        for key in ("question", "input", "query", "text"):
            value = raw.get(key)
            if isinstance(value, str) and value.strip():
                return value
    raise SystemExit(f"cannot extract question from dataset item input: {raw!r}")


def gold_dataset_rows() -> list[dict[str, Any]]:
    """Gold rows from knowledge.json, shaped for ``opengrade.evaluate(dataset=...)``.

    Extra keys land in item metadata (``expected_doc_ids`` for retrieval metrics,
    ``must_contain`` for the phrase check). Same rows → same dataset on every run.
    """
    return [
        {
            "input": row["question"],
            "expected_output": row["expected_output"],
            "expected_doc_ids": row["expected_doc_ids"],
            "must_contain": row["must_contain"],
        }
        for row in gold_rows_for_api()
    ]


DEFAULT_SYSTEM_PROMPT = (
    "You are Acme's People Ops assistant. Answer using only the provided "
    "policy context. Be concise (1-2 sentences). If the context is insufficient, "
    "say you do not know."
)


def system_prompt_from_params(params: dict[str, Any]) -> str | None:
    """``prompt.system`` from experiment params (an App Config snapshot has one)."""
    prompt = params.get("prompt")
    if not isinstance(prompt, dict):
        return None
    system = prompt.get("system")
    if isinstance(system, str) and system.strip():
        return system.strip()
    return None


def resolve_system_prompt(params: dict[str, Any] | None = None) -> str:
    env_prompt = os.getenv("OPENGRADE_SYSTEM_PROMPT")
    if isinstance(env_prompt, str) and env_prompt.strip():
        return env_prompt.strip()
    from_params = system_prompt_from_params(params or {})
    if from_params:
        return from_params
    return DEFAULT_SYSTEM_PROMPT


@opengrade.trace(
    name="people-ops-retrieve",
    kind="RETRIEVER",
    capture_input=False,
    capture_output=True,
)
def retrieve_traced(
    question: str, docs: list[dict[str, Any]], *, top_k: int = 2
) -> list[dict[str, Any]]:
    opengrade.set_input(question)
    hits = retrieve(docs, question, top_k=top_k)
    opengrade.set_retrieval_documents(
        [
            {
                "id": d["id"],
                "title": d.get("title"),
                "text": d.get("body") or "",
            }
            for d in hits
        ]
    )
    if not hits:
        opengrade.set_error("no documents")
    return hits


def call_ollama(
    client: OpenAI, *, model: str, user_prompt: str, system_prompt: str
) -> str:
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    return (response.choices[0].message.content or "").strip()


@opengrade.trace(
    name="people-ops-rag", kind="CHAIN", capture_input=False, capture_output=False
)
def answer_question(
    question: str,
    *,
    docs: list[dict[str, Any]],
    client: OpenAI,
    model: str,
    system_prompt: str,
) -> dict[str, Any]:
    opengrade.set_input(question)
    opengrade.set_attribute("llm.model", model)
    opengrade.set_attribute("llm.system_prompt_chars", len(system_prompt))

    hits = retrieve_traced(question, docs, top_k=2)
    if hits:
        context = "\n\n".join(
            f"Title: {d['title']}\n{d['body']}" for d in hits
        )
        user_prompt = f"Context:\n{context}\n\nQuestion: {question}\nAnswer:"
    else:
        user_prompt = (
            f"No policy context was retrieved.\n\nQuestion: {question}\nAnswer:"
        )

    answer = call_ollama(
        client, model=model, user_prompt=user_prompt, system_prompt=system_prompt
    )
    opengrade.set_output(answer)
    return {
        "question": question,
        "answer": answer,
        "model": model,
        "doc_ids": [d["id"] for d in hits],
        "trace_id": opengrade.current_trace_id() or "",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Acme People Ops Assistant → opengrade")
    parser.add_argument("question", nargs="?", help="User question")
    parser.add_argument(
        "--model",
        default=os.getenv("OLLAMA_MODEL", "gemma4:e2b"),
        help="Ollama model id",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Ask every gold question (traces only, no experiment)",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON result lines")
    parser.add_argument(
        "--eval",
        action="store_true",
        help="Run an experiment over --dataset (default: gold rows) and score it",
    )
    parser.add_argument(
        "--dataset",
        default=os.getenv("OPENGRADE_DATASET"),
        help="Dataset name or id for --eval (default: gold rows from knowledge.json)",
    )
    parser.add_argument("--name", help="Experiment name for --eval")
    parser.add_argument("--baseline", help="Baseline experiment name or id for --eval")
    parser.add_argument(
        "--app-config-id",
        help="App Config bound to the --eval experiment (its prompt.system is used)",
    )
    parser.add_argument(
        "--concurrency", type=int, default=1, help="Parallel questions for --eval"
    )
    args = parser.parse_args(argv)
    if not (args.eval or args.all or args.question):
        parser.error("provide a question, --all, or --eval")

    project_id = os.getenv("OPENGRADE_PROJECT_ID") or opengrade.set_project(
        os.getenv("OPENGRADE_PROJECT_SLUG", "hr-it-assistant")
    ).id
    opengrade.init(
        project_id=project_id,
        service_name=os.getenv("OPENGRADE_SERVICE_NAME", "hr-it-assistant"),
        instrument=["openai"],
    )

    docs = load_knowledge()
    host = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    client = OpenAI(
        base_url=f"{host}/v1",
        api_key=os.getenv("OLLAMA_API_KEY", "ollama"),
        timeout=float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "300")),
    )

    try:
        if args.eval:
            return run_eval(args, docs=docs, client=client)
        questions = [q for q, _, _ in iter_gold(docs)] if args.all else [args.question]
        system_prompt = resolve_system_prompt()
        for question in questions:
            result = answer_question(
                question,
                docs=docs,
                client=client,
                model=args.model,
                system_prompt=system_prompt,
            )
            result["expected_output"] = expected_for_question(docs, question)
            if args.json:
                print(json.dumps(result, ensure_ascii=True))
            else:
                print(f"[model={args.model}] trace={result['trace_id']}")
                print(f"Q: {result['question']}")
                print(f"A: {result['answer']}")
                print()
    finally:
        opengrade.flush()
    return 0


def run_eval(
    args: argparse.Namespace, *, docs: list[dict[str, Any]], client: OpenAI
) -> int:
    with opengrade.start_experiment(
        args.name or f"hr-it-assistant-{time.strftime('%Y%m%d-%H%M%S')}",
        dataset=args.dataset or gold_dataset_rows(),
        params={"model": args.model},
        baseline=args.baseline,
        app_config_id=args.app_config_id,
    ) as exp:
        # With an App Config, params are its snapshot: the prompt under test.
        system_prompt = resolve_system_prompt(exp.params)
        logger.info("using system prompt (%d chars)", len(system_prompt))
        print(f"experiment {exp.name}: {exp.url}", file=sys.stderr)

        def task(item: Any) -> str:
            result = answer_question(
                question_from_item_input(item.input),
                docs=docs,
                client=client,
                model=args.model,
                system_prompt=system_prompt,
            )
            return str(result["answer"])

        exp.run_task(task, max_concurrency=args.concurrency)

    result = exp.result
    assert result is not None
    if args.json:
        print(
            json.dumps(
                {
                    "experiment_id": result.id,
                    "status": result.status,
                    "url": result.url,
                    "metrics": result.metrics,
                    "errors": len(result.errors),
                },
                ensure_ascii=True,
            )
        )
    else:
        print(result.summary())
        print(result.url)
    for run in result.errors:
        print(f"item {run.item.id} failed: {run.error}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
