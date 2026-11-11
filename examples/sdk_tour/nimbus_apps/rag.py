"""The Nimbus support assistant: a small RAG pipeline instrumented with OpenGrade.

Read this file next to ``01_tracing.py``. The tracing code is only a few lines:

1. ``@og.trace`` on the entry point: one trace per question (a CHAIN span).
2. ``og.span(...)`` around each stage: retrieve -> generate, so the trace shows
   where time goes and what each stage received and returned.
3. ``og.set_retrieval_documents(docs)``: the documents the model saw. They feed
   the retrieval metrics (hit@k, recall@k, MRR) and the LLM judges (groundedness, ...),
   in experiments and in production alike.

Everything that can change between two versions of the pipeline (retriever, top_k,
model, prompt) lives in ``RagConfig``: that is what the tour compares in script 03.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any

from nimbus_apps.llm import generate_answer
from nimbus_apps.retrieval import search
from nimbus_apps.settings import DEFAULT_MODEL
from nimbus_apps.telemetry import og

PROMPTS = {
    "v1": "You are the Nimbus support assistant. Answer the question using the context.",
    "v2": (
        "You are the Nimbus support assistant. Answer in one or two sentences using ONLY "
        "the context. Cite the source id in square brackets, e.g. [plans]. If the context "
        "does not contain the answer, reply exactly: "
        '"I don\'t know: the Nimbus documentation does not cover this."'
    ),
}


@dataclass(frozen=True)
class RagConfig:
    retriever: str = "bm25"  # "keyword" | "bm25"  (see retrieval.py)
    top_k: int = 3  # documents passed to the model
    model: str = DEFAULT_MODEL  # "fake-small" | "fake-large" | any real model name
    prompt: str = "v2"  # key of PROMPTS

    def with_params(self, params: dict[str, Any]) -> RagConfig:
        """Copy with the fields found in ``params`` (used by sweeps)."""
        return replace(self, **{k: v for k, v in params.items() if k in asdict(self)})


DEFAULT_CONFIG = RagConfig()


def retrieve(question: str, config: RagConfig = DEFAULT_CONFIG) -> list[dict[str, Any]]:
    """Retrieval stage, traced as a RETRIEVER span."""
    with og.span("retrieve", kind="RETRIEVER", input=question) as span:
        docs = search(question, strategy=config.retriever, top_k=config.top_k)
        # Records the documents on this span: the platform reads them for retrieval
        # metrics and judges, and local metrics get them as ``Sample.documents``.
        og.set_retrieval_documents(docs)
        span.set_attributes(
            {"retrieval.strategy": config.retriever, "retrieval.top_k": config.top_k}
        )
        span.set_output([d["id"] for d in docs])
    return docs


def rewrite_search_query(history: list[dict[str, str]], question: str) -> str:
    """Turn a follow-up into a standalone retrieval query (demo rewrite).

    Uses the last user turn as topic context when the current question is short
    or referential (e.g. "How much does it cost?" after asking about Pro).
    """
    prior_user = next(
        (
            str(turn.get("content", "")).strip()
            for turn in reversed(history)
            if str(turn.get("role", "")).lower() == "user" and str(turn.get("content", "")).strip()
        ),
        "",
    )
    q = question.strip()
    if not prior_user:
        return q
    referential = len(q.split()) <= 8 or any(
        token in q.lower() for token in ("it", "that", "this", "they", "them", "those")
    )
    if referential:
        return f"{prior_user} {q}".strip()
    return q


@og.trace(name="support_assistant")
def answer_question(
    question: str,
    config: RagConfig = DEFAULT_CONFIG,
    *,
    system: str | None = None,
) -> str:
    """Answer one customer question. One call = one trace in OpenGrade.

    ``system`` overrides ``PROMPTS[config.prompt]`` when an App Config (or an A/B
    experiment) supplies the prompt under test.
    """
    og.set_input(question)
    system_prompt = system if system is not None else PROMPTS[config.prompt]
    og.set_metadata(**asdict(config), system_prompt_chars=len(system_prompt))

    docs = retrieve(question, config)
    with og.span("generate", kind="CHAIN", input=question) as span:
        answer = generate_answer(question, docs, model=config.model, system=system_prompt)
        span.set_output(answer)
    return answer


@og.trace(name="support_chat")
def answer_chat(
    history: list[dict[str, str]],
    question: str,
    config: RagConfig = DEFAULT_CONFIG,
    *,
    system: str | None = None,
) -> str:
    """Answer the last turn of a multi-turn support chat.

    Does not call ``set_session``: experiment runs must not land on the
    Production → Conversations timeline (the platform also filters them).
    """
    og.set_input({"history": history, "question": question})
    system_prompt = system if system is not None else PROMPTS[config.prompt]
    og.set_metadata(**asdict(config), system_prompt_chars=len(system_prompt), turns=len(history))

    search_query = rewrite_search_query(history, question)
    og.set_search_query(search_query)
    docs = retrieve(search_query, config)
    with og.span("generate", kind="CHAIN", input=question) as span:
        answer = generate_answer(question, docs, model=config.model, system=system_prompt)
        span.set_output(answer)
    return answer
