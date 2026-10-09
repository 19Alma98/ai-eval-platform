"""OpenInference / GenAI attribute helpers."""

from __future__ import annotations

from typing import Any

OPENINFERENCE_SPAN_KIND = "openinference.span.kind"

CONTENT_ATTRIBUTE_KEYS = frozenset(
    {
        "gen_ai.prompt",
        "gen_ai.completion",
        "gen_ai.input.messages",
        "gen_ai.output.messages",
        "llm.input_messages",
        "llm.output_messages",
        "llm.prompts",
        "llm.prompt_template.template",
        "llm.prompt_template.variables",
        "input.value",
        "output.value",
        "input.mime_type",
        "output.mime_type",
    }
)

_KIND_ALIASES: dict[str, str] = {
    "llm": "LLM",
    "embedding": "EMBEDDING",
    "embeddings": "EMBEDDING",
    "chain": "CHAIN",
    "tool": "TOOL",
    "retriever": "RETRIEVER",
    "retrieval": "RETRIEVER",
    "reranker": "RERANKER",
    "agent": "AGENT",
    "guardrail": "GUARDRAIL",
    "evaluator": "EVALUATOR",
    "span": "SPAN",
    "unknown": "SPAN",
}


def resolve_span_kind(attributes: dict[str, Any]) -> str:
    raw = attributes.get(OPENINFERENCE_SPAN_KIND)
    if raw is None:
        # GenAI operation type as weak fallback
        op = attributes.get("gen_ai.operation.name") or attributes.get("gen_ai.operation.type")
        if isinstance(op, str) and op.lower() in {"chat", "completion", "generate_content"}:
            return "LLM"
        if isinstance(op, str) and op.lower() in {"embeddings", "embedding"}:
            return "EMBEDDING"
        if isinstance(op, str) and op.lower() == "execute_tool":
            return "TOOL"
        return "SPAN"
    if not isinstance(raw, str):
        return "SPAN"
    return _KIND_ALIASES.get(raw.strip().lower(), raw.strip().upper() or "SPAN")


def extract_model_provider(attributes: dict[str, Any]) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    for key, out in (
        ("gen_ai.request.model", "model"),
        ("llm.model_name", "model"),
        ("gen_ai.system", "provider"),
        ("llm.provider", "provider"),
    ):
        value = attributes.get(key)
        if value is not None and out not in meta:
            meta[out] = value
    return meta
