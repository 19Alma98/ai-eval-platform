from __future__ import annotations

from dataclasses import dataclass

KNOWN_TASK_TYPES = frozenset({"rag_qa", "rag_chat", "classification", "agent_tools", "generic"})


@dataclass(frozen=True, slots=True)
class TaskTypeInfo:
    id: str
    label: str
    field_hints: tuple[str, ...]
    recommended_evaluator_kinds: tuple[str, ...]


TASK_TYPE_CATALOG: tuple[TaskTypeInfo, ...] = (
    TaskTypeInfo(
        id="rag_qa",
        label="RAG Q&A",
        field_hints=(
            "input: user question",
            "expected_output: reference answer",
            "metadata.expected_doc_ids: gold document ids (list or pipe-separated)",
            "metadata.must_contain: required answer phrases (optional, list or pipe-separated)",
            "context.documents / retrieval snippets",
            "actual_output: model answer",
        ),
        recommended_evaluator_kinds=(
            "hit_at_k",
            "recall_at_k",
            "mrr",
            "context_precision",
            "context_recall",
            "must_contain",
            "groundedness",
            "answer_relevance",
            "correctness",
            "citation_accuracy",
            "refusal",
            "pii",
            "toxicity",
            "prompt_injection",
            "latency",
        ),
    ),
    TaskTypeInfo(
        id="rag_chat",
        label="Conversational RAG",
        field_hints=(
            "input.history: prior {role, content} turns",
            "input.question: final user question",
            "expected_output: reference answer for the last turn",
            "metadata.expected_doc_ids: gold document ids for the last turn",
            "metadata.must_contain: required answer phrases (optional)",
            "context.documents / retrieval snippets for the last turn",
            "context.search_query: rewritten standalone retrieval query (optional)",
            "actual_output: model answer for the last turn",
        ),
        recommended_evaluator_kinds=(
            "hit_at_k",
            "recall_at_k",
            "mrr",
            "context_precision",
            "context_recall",
            "must_contain",
            "groundedness",
            "answer_relevance",
            "correctness",
            "citation_accuracy",
            "refusal",
            "pii",
            "toxicity",
            "prompt_injection",
            "query_rewrite_faithfulness",
            "conversation_consistency",
            "resolution",
            "latency",
        ),
    ),
    TaskTypeInfo(
        id="classification",
        label="Classification",
        field_hints=(
            "input: text to classify",
            "expected_output: label",
            "actual_output: predicted label",
        ),
        recommended_evaluator_kinds=("exact_match", "contains"),
    ),
    TaskTypeInfo(
        id="generic",
        label="Generic input → output",
        field_hints=(
            "input: what the app receives",
            "expected_output: reference output (optional)",
            "metadata.must_contain: required output phrases (optional)",
            "actual_output: what the app returned",
        ),
        recommended_evaluator_kinds=(
            "exact_match",
            "contains",
            "must_contain",
            "correctness",
            "latency",
        ),
    ),
    TaskTypeInfo(
        id="agent_tools",
        label="Agent / tools",
        field_hints=(
            "input: user goal",
            "context: tool call traces / attributes",
            "actual_output: final agent response",
        ),
        recommended_evaluator_kinds=(
            "tool_call_success",
            "correctness",
            "latency",
        ),
    ),
)


def normalize_task_type(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if cleaned not in KNOWN_TASK_TYPES:
        raise ValueError(
            f"Unknown task_type '{cleaned}'. Allowed: {', '.join(sorted(KNOWN_TASK_TYPES))}"
        )
    return cleaned


def get_task_type(task_type_id: str) -> TaskTypeInfo | None:
    for info in TASK_TYPE_CATALOG:
        if info.id == task_type_id:
            return info
    return None
