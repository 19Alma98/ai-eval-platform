"""Conversation-level RAG judges: query rewrite, consistency, resolution."""

from __future__ import annotations

from typing import Any

from opengrade_server.domain.rag_input import resolve_chat_history
from opengrade_server.domain.rag_models import ChatTurn
from opengrade_server.evaluation.judges import prompts
from opengrade_server.evaluation.judges.evaluators import _LlmJudge, _documents
from opengrade_server.evaluation.outcomes import skip
from opengrade_server.evaluation.protocol import EvaluationResult, EvaluationSample


def _search_query(sample: EvaluationSample) -> str | None:
    ctx = sample.context
    if isinstance(ctx, dict):
        for key in ("search_query", "rewritten_query", "retrieval_query"):
            value = ctx.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    meta = sample.metadata or {}
    for key in ("search_query", "rewritten_query", "retrieval_query"):
        value = meta.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _history_or_skip(
    sample: EvaluationSample, meta: dict[str, Any]
) -> list[ChatTurn] | EvaluationResult:
    try:
        from opengrade_server.domain.rag_models import RagChatInput

        raw = sample.input
        if isinstance(raw, RagChatInput):
            return resolve_chat_history(raw)
        if isinstance(raw, dict):
            return resolve_chat_history(raw)
        return []
    except ValueError as exc:
        return skip(str(exc), metadata=meta)


class QueryRewriteFaithfulnessJudge(_LlmJudge):
    kind = "query_rewrite_faithfulness"
    requires_answer = False

    def _precheck(self, sample: EvaluationSample) -> EvaluationResult | None:
        early = super()._precheck(sample)
        if early is not None:
            return early
        if _search_query(sample) is None:
            return skip(
                "search_query is missing (set via opengrade.set_search_query)",
                metadata=self._meta(),
            )
        return None

    async def _evaluate(self, sample: EvaluationSample) -> EvaluationResult:
        history = _history_or_skip(sample, self._meta())
        if isinstance(history, EvaluationResult):
            return history
        question = prompts.question_text(sample.input)
        query = _search_query(sample) or ""
        return await self._rubric(
            prompts.sections(
                conversation_history=prompts.render_history(history),
                question=question,
                search_query=query,
            )
        )


class ConversationConsistencyJudge(_LlmJudge):
    kind = "conversation_consistency"

    async def _evaluate(self, sample: EvaluationSample) -> EvaluationResult:
        history = _history_or_skip(sample, self._meta())
        if isinstance(history, EvaluationResult):
            return history
        question = prompts.question_text(sample.input)
        answer = prompts.as_text(sample.actual_output)
        turns: list[dict[str, str]] = [
            {
                "role": (t["role"] if isinstance(t, dict) else t.role),
                "content": (t["content"] if isinstance(t, dict) else t.content),
            }
            for t in history
        ]
        if question:
            turns.append({"role": "user", "content": question})
        if answer:
            turns.append({"role": "assistant", "content": answer})
        n_assistant = sum(1 for t in turns if t["role"] == "assistant")
        if n_assistant < 2:
            return skip(
                "fewer than two assistant turns; consistency is only scored on multi-turn dialogs",
                metadata=self._meta(),
            )
        return await self._rubric(
            prompts.sections(conversation=prompts.render_history(turns))
        )


class ResolutionJudge(_LlmJudge):
    kind = "resolution"

    def _precheck(self, sample: EvaluationSample) -> EvaluationResult | None:
        early = super()._precheck(sample)
        if early is not None:
            return early
        documents = _documents(sample.context)
        if not documents:
            return skip(
                "context.documents are missing or empty",
                metadata=self._meta(),
            )
        if not any(str(d.get("text") or "").strip() for d in documents):
            return skip(
                "retrieved documents have no text (only ids were stored, e.g. "
                "CONTENT_CAPTURE_ENABLED=false)",
                metadata=self._meta(),
            )
        return None

    async def _evaluate(self, sample: EvaluationSample) -> EvaluationResult:
        history = _history_or_skip(sample, self._meta())
        if isinstance(history, EvaluationResult):
            return history
        answer = prompts.as_text(sample.actual_output)
        question = prompts.question_text(sample.input)
        documents = prompts.render_documents(_documents(sample.context))
        user_turns = sum(
            1
            for turn in history
            if (turn["role"] if isinstance(turn, dict) else turn.role) == "user"
        ) + (1 if question else 0)
        result = await self._rubric(
            prompts.sections(
                conversation_history=prompts.render_history(history),
                question=question,
                documents=documents,
                answer=answer,
            )
        )
        meta = dict(result.metadata or {})
        resolved = (result.score or 0.0) >= 0.75
        meta["resolved"] = resolved
        if resolved:
            meta["turns_to_resolution"] = user_turns
        return EvaluationResult(
            score=result.score,
            label="resolved" if resolved else "unresolved",
            explanation=result.explanation,
            metadata=meta,
        )


CONVERSATION_JUDGES: dict[str, type[_LlmJudge]] = {
    QueryRewriteFaithfulnessJudge.kind: QueryRewriteFaithfulnessJudge,
    ConversationConsistencyJudge.kind: ConversationConsistencyJudge,
    ResolutionJudge.kind: ResolutionJudge,
}
