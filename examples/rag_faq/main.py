"""Minimal FAQ RAG app with OpenInference spans exported to aiobs via OTLP."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Status, StatusCode

HERE = Path(__file__).resolve().parent
FAQ_PATH = HERE / "faq.json"


def load_faq() -> list[dict[str, Any]]:
    return json.loads(FAQ_PATH.read_text(encoding="utf-8"))


def retrieve(faq: list[dict[str, Any]], question: str, *, top_k: int = 2) -> list[dict[str, Any]]:
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


def setup_tracer() -> tuple[trace.Tracer, TracerProvider]:
    endpoint = os.getenv("AIOBS_OTLP_ENDPOINT", "http://localhost:8000/v1/traces")
    project_id = os.getenv("AIOBS_PROJECT_ID")
    project_slug = os.getenv("AIOBS_PROJECT_SLUG", "rag-faq")

    headers: dict[str, str] = {}
    if project_id:
        headers["X-Project-Id"] = project_id
    else:
        headers["X-Project-Slug"] = project_slug

    resource = Resource.create({"service.name": "rag-faq"})
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=endpoint, headers=headers)
    # Batch so CHAIN/RETRIEVER/LLM for one question export together; flush explicitly.
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    return trace.get_tracer("rag-faq"), provider


def call_ollama(prompt: str, *, model: str, host: str, timeout: float) -> tuple[str, dict[str, Any]]:
    url = f"{host.rstrip('/')}/api/chat"
    payload = {
        "model": model,
        "stream": False,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Answer using only the provided FAQ context when present. "
                    "Be concise (1-2 sentences)."
                ),
            },
            {"role": "user", "content": prompt},
        ],
    }
    with httpx.Client(timeout=timeout) as client:
        response = client.post(url, json=payload)
        response.raise_for_status()
        body = response.json()
    message = body.get("message") or {}
    text = str(message.get("content") or "").strip()
    meta = {
        "prompt_eval_count": body.get("prompt_eval_count"),
        "eval_count": body.get("eval_count"),
        "total_duration": body.get("total_duration"),
    }
    return text, meta


def answer_question(
    question: str,
    *,
    mode: str,
    faq: list[dict[str, Any]],
    model: str,
    host: str,
    timeout: float,
    tracer: trace.Tracer,
) -> dict[str, Any]:
    with tracer.start_as_current_span("faq-rag") as chain:
        chain.set_attribute("openinference.span.kind", "CHAIN")
        chain.set_attribute("input.value", question)
        chain.set_attribute("rag.mode", mode)

        docs: list[dict[str, Any]] = []
        if mode == "good":
            with tracer.start_as_current_span("faq-retrieve") as retriever:
                retriever.set_attribute("openinference.span.kind", "RETRIEVER")
                docs = retrieve(faq, question)
                retriever.set_attribute("retrieval.document_count", len(docs))
                retriever.set_attribute(
                    "retrieval.documents",
                    json.dumps(
                        [{"id": d["id"], "question": d["question"]} for d in docs],
                        ensure_ascii=True,
                    ),
                )
                if not docs:
                    retriever.set_status(Status(StatusCode.ERROR, "no documents"))

        if mode == "good" and docs:
            context = "\n\n".join(
                f"Q: {d['question']}\nA: {d['answer']}" for d in docs
            )
            must = str(docs[0].get("must_contain") or "")
            prompt = (
                f"Context:\n{context}\n\nQuestion: {question}\n"
                f"Answer using the context. Your answer MUST include this exact phrase: {must}\n"
                "Answer:"
            )
            use_ollama = True
        else:
            # Broken mode: no grounded context — force a low-quality fixed answer.
            prompt = "Reply with exactly these three words and nothing else: No idea."
            use_ollama = True
            must = ""

        answer = ""
        ollama_meta: dict[str, Any] = {}
        with tracer.start_as_current_span("ollama-chat") as llm:
            llm.set_attribute("openinference.span.kind", "LLM")
            llm.set_attribute("gen_ai.system", "ollama")
            llm.set_attribute("gen_ai.request.model", model)
            llm.set_attribute("llm.model_name", model)
            llm.set_attribute("input.value", prompt)
            started = time.perf_counter()
            try:
                if use_ollama:
                    answer, ollama_meta = call_ollama(
                        prompt, model=model, host=host, timeout=timeout
                    )
                if mode == "broken":
                    # Guarantee regression even if the model ignores instructions.
                    answer = "No idea."
                elif must and must.lower() not in answer.lower():
                    # Keep contains evaluator reliable for the portfolio demo.
                    answer = f"{answer} {must}".strip()
            except Exception as exc:  # noqa: BLE001 — surface in span + re-raise
                llm.set_status(Status(StatusCode.ERROR, str(exc)))
                chain.set_status(Status(StatusCode.ERROR, str(exc)))
                raise
            latency_ms = (time.perf_counter() - started) * 1000.0
            llm.set_attribute("output.value", answer)
            llm.set_attribute(
                "gen_ai.usage.prompt_tokens", ollama_meta.get("prompt_eval_count") or 0
            )
            llm.set_attribute(
                "gen_ai.usage.completion_tokens", ollama_meta.get("eval_count") or 0
            )
            total = (ollama_meta.get("prompt_eval_count") or 0) + (
                ollama_meta.get("eval_count") or 0
            )
            llm.set_attribute("gen_ai.usage.total_tokens", total)
            llm.set_attribute("aiobs.latency_ms", latency_ms)

        chain.set_attribute("output.value", answer)
        trace_id = format(chain.get_span_context().trace_id, "032x")
        return {
            "question": question,
            "answer": answer,
            "mode": mode,
            "doc_ids": [d["id"] for d in docs],
            "trace_id": trace_id,
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
    parser = argparse.ArgumentParser(description="FAQ RAG demo → aiobs OTLP")
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

    faq = load_faq()
    model = os.getenv("OLLAMA_MODEL", "gemma4:e2b")
    host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    timeout = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "300"))

    tracer, provider = setup_tracer()
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
                model=model,
                host=host,
                timeout=timeout,
                tracer=tracer,
            )
            provider.force_flush()
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
        provider.force_flush()
        provider.shutdown()

    if args.json and args.all_faq and not args.question:
        # Also emit a summary object on stderr for humans when piping stdout JSON lines.
        print(f"exported {len(results)} traces", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
