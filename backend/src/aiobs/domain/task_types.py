from __future__ import annotations

from dataclasses import dataclass

KNOWN_TASK_TYPES = frozenset({"rag_qa", "classification", "agent_tools"})


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
            "context.documents / retrieval snippets",
            "expected_output: reference answer",
            "actual_output: model answer",
        ),
        recommended_evaluator_kinds=(
            "groundedness",
            "answer_relevance",
            "correctness",
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
