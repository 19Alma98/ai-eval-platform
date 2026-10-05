"""Acme People Ops Assistant — FAQ RAG demo via aiobs SDK + Ollama."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import aiobs
from openai import OpenAI

from kb import expected_for_question, iter_gold, load_knowledge, retrieve

SYSTEM_PROMPT = (
    "You are Acme's People Ops assistant. Answer using only the provided "
    "policy context. Be concise (1-2 sentences). If the context is insufficient, "
    "say you do not know."
)


@aiobs.trace(
    name="people-ops-retrieve",
    kind="RETRIEVER",
    capture_input=False,
    capture_output=True,
)
def retrieve_traced(
    question: str, docs: list[dict[str, Any]], *, top_k: int = 2
) -> list[dict[str, Any]]:
    aiobs.set_input(question)
    hits = retrieve(docs, question, top_k=top_k)
    if hits:
        aiobs.set_retrieval_documents(
            [
                {
                    "id": d["id"],
                    "title": d.get("title"),
                    "text": d.get("body") or "",
                }
                for d in hits
            ]
        )
    else:
        aiobs.set_attributes({"retrieval.document_count": 0})
    if not hits:
        aiobs.set_error("no documents")
    return hits


def call_ollama(client: OpenAI, *, model: str, user_prompt: str) -> str:
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    )
    return (response.choices[0].message.content or "").strip()


@aiobs.trace(
    name="people-ops-rag", kind="CHAIN", capture_input=False, capture_output=False
)
def answer_question(
    question: str,
    *,
    docs: list[dict[str, Any]],
    client: OpenAI,
    model: str,
    experiment_id: str | None = None,
    dataset_item_id: str | None = None,
) -> dict[str, Any]:
    if experiment_id and dataset_item_id:
        aiobs.bind_evaluation(
            experiment_id=experiment_id, dataset_item_id=dataset_item_id
        )
    aiobs.set_input(question)
    aiobs.set_attribute("llm.model", model)

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

    answer = call_ollama(client, model=model, user_prompt=user_prompt)
    aiobs.set_output(answer)
    return {
        "question": question,
        "answer": answer,
        "model": model,
        "doc_ids": [d["id"] for d in hits],
        "trace_id": aiobs.current_trace_id() or "",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Acme People Ops Assistant → aiobs")
    parser.add_argument("question", nargs="?", help="User question")
    parser.add_argument(
        "--model",
        default=os.getenv("OLLAMA_MODEL", "gemma4:e2b"),
        help="Ollama model id",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Ask every gold question (used by portfolio_demo)",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON result lines")
    parser.add_argument(
        "--experiment-id",
        default=os.getenv("AIOBS_EXPERIMENT_ID"),
        help="Run id to bind traces to (SDK bind_evaluation)",
    )
    parser.add_argument(
        "--item-map",
        type=Path,
        default=None,
        help="JSON map question text -> dataset_item_id for --all runs",
    )
    args = parser.parse_args(argv)

    item_map: dict[str, str] = {}
    if args.item_map is not None:
        item_map = json.loads(args.item_map.read_text(encoding="utf-8"))
        if not isinstance(item_map, dict):
            raise SystemExit("--item-map must be a JSON object")

    project_id = os.getenv("AIOBS_PROJECT_ID")
    project_slug = os.getenv("AIOBS_PROJECT_SLUG", "hr-it-assistant")
    init_kwargs: dict[str, Any] = {
        "endpoint": os.getenv("AIOBS_OTLP_ENDPOINT", "http://localhost:8000/v1/traces"),
        "service_name": os.getenv("AIOBS_SERVICE_NAME", "hr-it-assistant"),
        "instrument": ["openai"],
    }
    if project_id:
        init_kwargs["project_id"] = project_id
    else:
        init_kwargs["project_slug"] = project_slug
    aiobs.init(**init_kwargs)

    docs = load_knowledge()
    host = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    client = OpenAI(
        base_url=f"{host}/v1",
        api_key=os.getenv("OLLAMA_API_KEY", "ollama"),
        timeout=float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "300")),
    )

    if args.all:
        questions = [q for q, _, _ in iter_gold(docs)]
    elif args.question:
        questions = [args.question]
    else:
        parser.error("provide a question or --all")

    try:
        for question in questions:
            item_id = item_map.get(question) if item_map else None
            result = answer_question(
                question,
                docs=docs,
                client=client,
                model=args.model,
                experiment_id=args.experiment_id,
                dataset_item_id=item_id,
            )
            aiobs.flush()
            result["expected_output"] = expected_for_question(docs, question)
            if args.json:
                print(json.dumps(result, ensure_ascii=True))
            else:
                print(f"[model={args.model}] trace={result['trace_id']}")
                print(f"Q: {result['question']}")
                print(f"A: {result['answer']}")
                print()
    finally:
        aiobs.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
