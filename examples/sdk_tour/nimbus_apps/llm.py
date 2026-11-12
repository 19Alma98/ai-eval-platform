"""LLM layer: a real OpenAI-compatible client, or an offline "fake" model.

- Real models (any name not starting with ``fake-``) are called through the ``openai``
  client against ``LLM_BASE_URL`` (Ollama by default). You write no tracing code for
  them: ``og.init_tracing(instrument="auto")`` activates the OpenInference instrumentor,
  which records every call as an LLM span with model, prompt, tokens and latency.
- ``fake-small`` / ``fake-large`` are deterministic stand-ins so the whole tour runs
  without a GPU or an API key. They are also an example of how to trace a provider that
  has no auto-instrumentation: open an ``LLM`` span yourself and set the OpenInference
  attributes (model name, token counts, cost) that the platform aggregates.

``fake-small`` answers with the first sentence of the first document and never refuses;
``fake-large`` picks the sentence that best matches the question and refuses when
nothing matches. The difference is what the comparisons in the tour will measure.
"""

from __future__ import annotations

import re
import time
from functools import cache
from typing import Any

from nimbus_apps.retrieval import tokenize
from nimbus_apps.settings import LLM_API_KEY, LLM_BASE_URL
from nimbus_apps.telemetry import og

REFUSAL = "I don't know: the Nimbus documentation does not cover this."

# Fake price list (USD per 1K tokens) and latency, so cost/latency charts have data.
_FAKE_MODELS = {
    "fake-small": {"usd_per_1k_tokens": 0.0002, "latency_s": 0.01},
    "fake-large": {"usd_per_1k_tokens": 0.002, "latency_s": 0.04},
}


def is_fake(model: str) -> bool:
    return model.startswith("fake-")


# --------------------------------------------------------------------------- real LLM


@cache
def _openai_client() -> Any:
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover - depends on the installed extras
        raise RuntimeError(
            "Real models need the 'llm' extra: uv sync --extra llm "
            "(or set TOUR_MODEL=fake-large to stay offline)"
        ) from exc
    return OpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY)


def chat(model: str, system: str, user: str, *, temperature: float = 0.0) -> str:
    """One chat completion. The OpenAI instrumentor turns it into an LLM span."""
    response = _openai_client().chat.completions.create(
        model=model,
        temperature=temperature,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
    )
    return response.choices[0].message.content or ""


# --------------------------------------------------------------------------- fake LLM


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def _fake_answer(
    model: str,
    question: str,
    docs: list[dict[str, Any]],
    *,
    match_query: str | None = None,
) -> str:
    if not docs:
        return REFUSAL
    if model == "fake-small":
        first = docs[0]
        return f"{_sentences(str(first['text']))[0]} [{first['id']}]"
    query = set(tokenize(match_query or question))
    candidates = [
        (len(query & set(tokenize(sentence))), -rank, sentence, doc["id"])
        for rank, doc in enumerate(docs)
        for sentence in _sentences(str(doc["text"]))
    ]
    overlap, _, sentence, doc_id = max(candidates)
    if overlap < 2:
        return REFUSAL
    return f"{sentence} [{doc_id}]"


def _fake_llm_call(
    model: str,
    prompt: str,
    question: str,
    docs: list[dict[str, Any]],
    *,
    match_query: str | None = None,
) -> str:
    """Run the fake model inside a hand-made LLM span (what an instrumentor would do)."""
    spec = _FAKE_MODELS.get(model)
    if spec is None:
        raise ValueError(f"unknown fake model {model!r}; choose one of {sorted(_FAKE_MODELS)}")
    with og.span("llm.chat", kind="LLM", input=prompt) as span:
        time.sleep(spec["latency_s"])
        answer = _fake_answer(model, question, docs, match_query=match_query)
        prompt_tokens = len(prompt.split())
        completion_tokens = len(answer.split())
        total = prompt_tokens + completion_tokens
        span.set_output(answer)
        # OpenInference attribute names: the platform sums tokens and cost per trace.
        span.set_attributes(
            {
                "llm.model_name": model,
                "llm.provider": "fake",
                "llm.token_count.prompt": prompt_tokens,
                "llm.token_count.completion": completion_tokens,
                "llm.token_count.total": total,
                "llm.cost": round(total / 1000 * spec["usd_per_1k_tokens"], 8),
            }
        )
    return answer


# --------------------------------------------------------------------------- public API


def format_history(history: list[dict[str, str]] | None) -> str:
    if not history:
        return ""
    lines: list[str] = []
    for turn in history:
        role = str(turn.get("role", "user")).strip().lower() or "user"
        content = str(turn.get("content", "")).strip()
        if not content:
            continue
        label = "User" if role == "user" else "Assistant" if role == "assistant" else role.title()
        lines.append(f"{label}: {content}")
    return "\n".join(lines)


def build_prompt(
    question: str,
    docs: list[dict[str, Any]],
    *,
    history: list[dict[str, str]] | None = None,
) -> str:
    context = "\n".join(f"[{d['id']}] {d['text']}" for d in docs) or "(no documents)"
    prior = format_history(history)
    if prior:
        return (
            f"Context:\n{context}\n\nConversation so far:\n{prior}\n\n"
            f"Latest user question: {question}"
        )
    return f"Context:\n{context}\n\nQuestion: {question}"


def generate_answer(
    question: str,
    docs: list[dict[str, Any]],
    *,
    model: str,
    system: str,
    history: list[dict[str, str]] | None = None,
    match_query: str | None = None,
) -> str:
    """Answer ``question`` from ``docs`` with ``model`` (fake or real / Ollama).

    ``history`` is included in the prompt for multi-turn chat (needed by real models).
    ``match_query`` is the rewritten standalone query used by fake-large for sentence
    overlap (same string retrieval used).
    """
    prompt = build_prompt(question, docs, history=history)
    if is_fake(model):
        return _fake_llm_call(
            model, f"{system}\n\n{prompt}", question, docs, match_query=match_query
        )
    return chat(model, system, prompt)
