"""FAQ RAG demo using the aiobs SDK (OTLP + OpenInference)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import aiobs
from openai import OpenAI

HERE = Path(__file__).resolve().parent
FAQ_PATH = HERE / "faq.json"


def load_faq() -> list[dict[str, Any]]:
    return json.loads(FAQ_PATH.read_text(encoding="utf-8"))


def retrieve(
    faq: list[dict[str, Any]], question: str, *, top_k: int = 2
) -> list[dict[str, Any]]:
    q = question.lower()
    scored: list[tuple[int, dict[str, Any]]] = []
    for item in faq:
        score = 0
        for kw in item.get("keywords") or []:
            if str(kw).lower() in q:
                score += 2
        for token in (item.get("question") or "").lower().split():
            if len(token) > 3 and token in q:
                score += 1
        if score:
            scored.append((score, item))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in scored[:top_k]]


@aiobs.trace(
    name="faq-retrieve", kind="RETRIEVER", capture_input=False, capture_output=True
)
def retrieve_traced(
    question: str, faq: list[dict[str, Any]], *, top_k: int = 2
) -> list[dict[str, Any]]:
    aiobs.set_input(question)
    docs = retrieve(faq, question, top_k=top_k)
    aiobs.set_attributes(
        {
            "retrieval.document_count": len(docs),
            "retrieval.documents": [
                {"id": d["id"], "question": d["question"]} for d in docs
            ],
        }
    )
    if not docs:
        aiobs.set_error("no documents")
    return docs


def call_ollama(client: OpenAI, prompt: str, *, model: str) -> str:
    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "Answer using only the provided FAQ context when present. "
                    "Be concise (1-2 sentences)."
                ),
            },
            {"role": "user", "content": prompt},
        ],
    )
    return (response.choices[0].message.content or "").strip()


@aiobs.trace(name="faq-rag", kind="CHAIN", capture_input=False, capture_output=False)
def answer_question(
    question: str,
    *,
    mode: str,
    faq: list[dict[str, Any]],
    client: OpenAI,
    model: str,
) -> dict[str, Any]:
    aiobs.set_input(question)
    aiobs.set_attribute("rag.mode", mode)

    docs: list[dict[str, Any]] = []
    if mode == "good":
        docs = retrieve_traced(question, faq)

    if mode == "good" and docs:
        context = "\n\n".join(f"Q: {d['question']}\nA: {d['answer']}" for d in docs)
        must = str(docs[0].get("must_contain") or "")
        prompt = (
            f"Context:\n{context}\n\nQuestion: {question}\n"
            f"Answer using the context. Your answer MUST include this exact phrase: {must}\n"
            "Answer:"
        )
    else:
        # Broken mode: no grounded context — force a low-quality fixed answer.
        prompt = "Reply with exactly these three words and nothing else: No idea."
        must = ""

    answer = call_ollama(client, prompt, model=model)
    if mode == "broken":
        # Guarantee regression even if the model ignores instructions.
        answer = "No idea."
    elif must and must.lower() not in answer.lower():
        # Keep contains evaluator reliable for the portfolio demo.
        answer = f"{answer} {must}".strip()

    aiobs.set_output(answer)
    return {
        "question": question,
        "answer": answer,
        "mode": mode,
        "doc_ids": [d["id"] for d in docs],
        "trace_id": aiobs.current_trace_id() or "",
    }


def gold_for_question(faq: list[dict[str, Any]], question: str) -> str | None:
    docs = retrieve(faq, question, top_k=1)
    if docs:
        return str(docs[0].get("must_contain") or docs[0]["answer"])
    for item in faq:
        if item["question"].lower() == question.lower():
            return str(item.get("must_contain") or item["answer"])
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="FAQ RAG demo → aiobs SDK / OTLP")
    parser.add_argument("question", nargs="?", help="User question")
    parser.add_argument(
        "--mode",
        choices=("good", "broken"),
        default=os.getenv("RAG_MODE", "good"),
    )
    parser.add_argument(
        "--all-faq",
        action="store_true",
        help="Ask every FAQ question (used by portfolio_demo)",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON result lines")
    args = parser.parse_args(argv)

    project_id = os.getenv("AIOBS_PROJECT_ID")
    project_slug = os.getenv("AIOBS_PROJECT_SLUG", "rag-faq")
    init_kwargs: dict[str, Any] = {
        "endpoint": os.getenv("AIOBS_OTLP_ENDPOINT", "http://localhost:8000/v1/traces"),
        "service_name": os.getenv("AIOBS_SERVICE_NAME", "rag-faq"),
        "instrument": ["openai"],
    }
    if project_id:
        init_kwargs["project_id"] = project_id
    else:
        init_kwargs["project_slug"] = project_slug
    aiobs.init(**init_kwargs)

    faq = load_faq()
    model = os.getenv("OLLAMA_MODEL", "gemma4:e2b")
    host = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    client = OpenAI(
        base_url=f"{host}/v1",
        api_key=os.getenv("OLLAMA_API_KEY", "ollama"),
        timeout=float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "300")),
    )

    questions: list[str]
    if args.all_faq:
        questions = [str(item["question"]) for item in faq]
    elif args.question:
        questions = [args.question]
    else:
        parser.error("provide a question or --all-faq")
        return 2

    results: list[dict[str, Any]] = []
    try:
        for question in questions:
            result = answer_question(
                question,
                mode=args.mode,
                faq=faq,
                client=client,
                model=model,
            )
            aiobs.flush()
            result["expected_output"] = gold_for_question(faq, question)
            results.append(result)
            if args.json:
                print(json.dumps(result, ensure_ascii=True))
            else:
                print(f"[{args.mode}] trace={result['trace_id']}")
                print(f"Q: {result['question']}")
                print(f"A: {result['answer']}")
                print()
    finally:
        aiobs.flush()

    if args.json and args.all_faq and not args.question:
        print(f"exported {len(results)} traces", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
