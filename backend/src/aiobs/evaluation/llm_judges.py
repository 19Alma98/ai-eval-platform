from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from aiobs.evaluation.outcomes import fail_min, skip
from aiobs.evaluation.protocol import EvaluationResult, EvaluationSample, LlmClient


def _groundedness_documents_missing_or_empty(context: Any) -> bool:
    if not isinstance(context, dict):
        return True
    if "documents" not in context:
        return True
    documents = context["documents"]
    if documents is None:
        return True
    if not isinstance(documents, list):
        return True
    return len(documents) == 0


PROMPT_VERSIONS = {
    "answer_relevance": "answer_relevance.v2",
    "groundedness": "groundedness.v2",
    "correctness": "correctness.v2",
}

_SYSTEM_PROMPTS = {
    "answer_relevance": (
        "You are an evaluation judge. Score how relevant the actual_output is to the input. "
        "Respond with JSON only: "
        '{"score": <float 0..1>, "label": "PASS"|"FAIL", "explanation": "<short reason>"}.'
    ),
    "groundedness": (
        "You are an evaluation judge. Score how grounded the actual_output is in the provided "
        "context (no unsupported claims). Respond with JSON only: "
        '{"score": <float 0..1>, "label": "PASS"|"FAIL", "explanation": "<short reason>"}.'
    ),
    "correctness": (
        "You are an evaluation judge. Score correctness of actual_output versus expected_output. "
        "Respond with JSON only: "
        '{"score": <float 0..1>, "label": "PASS"|"FAIL", "explanation": "<short reason>"}.'
    ),
}


def _build_user_payload(kind: str, sample: EvaluationSample) -> str:
    """Send each judge only what its rubric needs.

    Gold (expected_output, metadata such as expected_doc_ids) never reaches the
    gold-less judges, so offline and live scores stay comparable and unbiased.
    """
    payload: dict[str, Any] = {"input": sample.input, "actual_output": sample.actual_output}
    if kind == "correctness":
        payload["expected_output"] = sample.expected_output
    elif kind == "groundedness":
        documents = sample.context.get("documents") if isinstance(sample.context, dict) else None
        payload["context"] = {"documents": documents}
    return json.dumps(payload, default=str)


class LlmJudgeEvaluator:
    def __init__(
        self,
        kind: str,
        config: dict[str, Any],
        llm: LlmClient,
        *,
        default_model: str | None = None,
    ) -> None:
        if kind not in _SYSTEM_PROMPTS:
            raise ValueError(f"Unknown LLM judge kind: {kind}")
        self.name = kind
        self._kind = kind
        self._config = config
        self._llm = llm
        self._model = config.get("model") or default_model
        self._prompt_version = PROMPT_VERSIONS[kind]

    async def evaluate(self, sample: EvaluationSample) -> EvaluationResult:
        if sample.actual_output is None:
            return skip("actual_output is missing")
        if self._kind == "correctness" and sample.expected_output is None:
            return skip("expected_output is missing")
        if self._kind == "groundedness":
            if sample.context is None:
                return skip("context is missing")
            if _groundedness_documents_missing_or_empty(sample.context):
                return fail_min("context.documents are missing or empty")

        raw = await self._llm.complete_json(
            system=_SYSTEM_PROMPTS[self._kind],
            user=_build_user_payload(self._kind, sample),
            model=self._model,
        )
        score = raw.get("score")
        if score is not None:
            try:
                score = float(score)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Judge returned non-numeric score: {score!r}") from exc
            if score < 0 or score > 1:
                raise ValueError(f"Judge score out of range [0,1]: {score}")

        label = raw.get("label")
        if label is not None:
            label = str(label)
        explanation = raw.get("explanation")
        if explanation is not None:
            explanation = str(explanation)

        return EvaluationResult(
            score=score,
            label=label,
            explanation=explanation,
            metadata={
                "prompt_version": self._prompt_version,
                "model": self._model,
                "judge_kind": self._kind,
                "raw": raw,
            },
        )


def make_llm_judge_factory(
    kind: str,
    llm: LlmClient,
    *,
    default_model: str | None = None,
) -> Callable[[dict[str, Any]], LlmJudgeEvaluator]:
    def factory(config: dict[str, Any]) -> LlmJudgeEvaluator:
        return LlmJudgeEvaluator(kind, config, llm, default_model=default_model)

    return factory
