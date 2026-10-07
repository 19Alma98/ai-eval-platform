"""Acme People Ops Assistant — FAQ RAG demo via aiobs SDK + Ollama."""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from kb import expected_for_question, iter_gold, load_knowledge, retrieve
from openai import OpenAI

import aiobs
from aiobs import Client

logger = logging.getLogger(__name__)


def api_client() -> Client:
    return Client(
        os.getenv("AIOBS_API_BASE_URL") or os.getenv("AIOBS_BASE_URL"),
        timeout=60.0,
    )


def question_from_item_input(raw: Any) -> str:
    if isinstance(raw, str) and raw.strip():
        return raw
    if isinstance(raw, dict):
        for key in ("question", "input", "query", "text"):
            value = raw.get(key)
            if isinstance(value, str) and value.strip():
                return value
    raise SystemExit(f"cannot extract question from dataset item input: {raw!r}")


def load_dataset_jobs(dataset_id: str) -> tuple[str, list[tuple[str, str, Any]]]:
    detail = api_client().datasets.get(dataset_id)
    items = detail.get("items") or []
    if not items:
        raise SystemExit(f"dataset {dataset_id} has no items")
    jobs: list[tuple[str, str, Any]] = []
    for item in items:
        jobs.append(
            (
                question_from_item_input(item.get("input")),
                str(item["id"]),
                item.get("expected_output"),
            )
        )
    return str(detail["project_id"]), jobs


def create_experiment(project_id: str, dataset_id: str, *, model: str) -> str:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    experiment = api_client().experiments.create(
        project_id,
        name=f"hr-it-assistant-{stamp}",
        dataset_id=dataset_id,
        model_config={"model": model},
        version=stamp,
    )
    return str(experiment["id"])


DEFAULT_SYSTEM_PROMPT = (
    "You are Acme's People Ops assistant. Answer using only the provided "
    "policy context. Be concise (1-2 sentences). If the context is insufficient, "
    "say you do not know."
)

# Back-compat alias for importers / docs that expect SYSTEM_PROMPT.
SYSTEM_PROMPT = DEFAULT_SYSTEM_PROMPT


def system_prompt_from_experiment(experiment_id: str) -> str | None:
    detail = api_client().experiments.get(experiment_id)
    mc = detail.get("model_config") or {}
    prompt = mc.get("prompt") if isinstance(mc, dict) else None
    if not isinstance(prompt, dict):
        return None
    system = prompt.get("system")
    if isinstance(system, str) and system.strip():
        return system.strip()
    return None


def resolve_system_prompt(*, experiment_id: str | None) -> str:
    env_prompt = os.getenv("AIOBS_SYSTEM_PROMPT")
    if isinstance(env_prompt, str) and env_prompt.strip():
        return env_prompt.strip()
    if experiment_id:
        from_exp = system_prompt_from_experiment(experiment_id)
        if from_exp:
            return from_exp
    return DEFAULT_SYSTEM_PROMPT


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
    if not hits:
        aiobs.set_error("no documents")
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


@aiobs.trace(
    name="people-ops-rag", kind="CHAIN", capture_input=False, capture_output=False
)
def answer_question(
    question: str,
    *,
    docs: list[dict[str, Any]],
    client: OpenAI,
    model: str,
    system_prompt: str,
    experiment_id: str | None = None,
    dataset_item_id: str | None = None,
) -> dict[str, Any]:
    if experiment_id and dataset_item_id:
        aiobs.bind_evaluation(
            experiment_id=experiment_id, dataset_item_id=dataset_item_id
        )
    elif experiment_id:
        logger.warning(
            "experiment_id=%s set but dataset_item_id missing; "
            "trace will not be bound to an evaluation item",
            experiment_id,
        )
    aiobs.set_input(question)
    aiobs.set_attribute("llm.model", model)
    aiobs.set_attribute("llm.system_prompt_chars", len(system_prompt))

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
        help="Experiment id to bind traces to (SDK bind_evaluation)",
    )
    parser.add_argument(
        "--item-map",
        type=Path,
        default=None,
        help="JSON map question text -> dataset_item_id for --all runs",
    )
    parser.add_argument(
        "--dataset-id",
        default=os.getenv("AIOBS_DATASET_ID"),
        help="Load questions from this dataset and bind each trace to its item",
    )
    args = parser.parse_args(argv)

    item_map: dict[str, str] = {}
    if args.item_map is not None:
        item_map = json.loads(args.item_map.read_text(encoding="utf-8"))
        if not isinstance(item_map, dict):
            raise SystemExit("--item-map must be a JSON object")

    dataset_jobs: list[tuple[str, str, Any]] | None = None
    dataset_project_id: str | None = None
    if args.dataset_id:
        dataset_project_id, dataset_jobs = load_dataset_jobs(args.dataset_id)

    project_id = os.getenv("AIOBS_PROJECT_ID") or dataset_project_id
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

    experiment_id = args.experiment_id
    jobs: list[tuple[str, str | None, Any]]
    if dataset_jobs is not None:
        if not experiment_id:
            if not project_id:
                raise SystemExit(
                    "dataset run needs project_id from the dataset or AIOBS_PROJECT_ID"
                )
            experiment_id = create_experiment(
                project_id, args.dataset_id, model=args.model
            )
            print(f"created experiment {experiment_id} for dataset {args.dataset_id}")
        jobs = [(q, item_id, expected) for q, item_id, expected in dataset_jobs]
    elif args.all:
        jobs = [(q, item_map.get(q), None) for q, _, _ in iter_gold(docs)]
    elif args.question:
        jobs = [(args.question, item_map.get(args.question) if item_map else None, None)]
    else:
        parser.error("provide a question, --all, or --dataset-id")

    system_prompt = resolve_system_prompt(experiment_id=experiment_id)
    logger.info("using system prompt (%d chars)", len(system_prompt))

    try:
        for question, item_id, expected_output in jobs:
            result = answer_question(
                question,
                docs=docs,
                client=client,
                model=args.model,
                system_prompt=system_prompt,
                experiment_id=experiment_id,
                dataset_item_id=item_id,
            )
            aiobs.flush()
            result["expected_output"] = (
                expected_output
                if expected_output is not None
                else expected_for_question(docs, question)
            )
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
