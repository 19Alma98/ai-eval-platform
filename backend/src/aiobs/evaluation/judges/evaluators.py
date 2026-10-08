from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from aiobs.domain.repositories import JudgeClaimCacheRepository
from aiobs.evaluation.judges import prompts
from aiobs.evaluation.judges.cache import claim_cache_key
from aiobs.evaluation.judges.claims import (
    ExtractedClaims,
    average_precision,
    coverage_claim_records,
    extract_claims,
    f1,
    limit_claims,
    score_coverage,
    score_support,
    support_claim_records,
    verify_coverage,
    verify_relevance,
    verify_support,
)
from aiobs.evaluation.judges.errors import (
    JUDGE_OUTPUT_INVALID,
    JudgeOutputError,
    classify_llm_error,
)
from aiobs.evaluation.judges.parsing import CallOptions
from aiobs.evaluation.judges.rubric import level_to_score, rubric_judge
from aiobs.evaluation.outcomes import error, fail_min, skip
from aiobs.evaluation.protocol import EvaluationResult, EvaluationSample, LlmClient

JUDGE_KINDS = ("answer_relevance", "groundedness", "correctness", "context_precision")

_METHODS: dict[str, frozenset[str]] = {
    "groundedness": frozenset({"claims", "rubric"}),
    "correctness": frozenset({"claims", "rubric"}),
    "answer_relevance": frozenset({"rubric"}),
    "context_precision": frozenset({"claims", "rubric"}),
}
_DEFAULT_METHOD = {
    "groundedness": "claims",
    "correctness": "claims",
    "answer_relevance": "rubric",
    "context_precision": "claims",
}
_SCORINGS = frozenset({"recall", "f1"})
DEFAULT_MAX_CLAIMS = 30
_RAW_OUTPUT_LIMIT = 2000
_QUOTED_CLAIMS = 3
_QUOTED_CLAIM_CHARS = 200
_EXPLANATION_LIMIT = 1000


@dataclass(frozen=True, slots=True)
class JudgeDefaults:
    model: str | None = None


@dataclass(frozen=True, slots=True)
class JudgeConfig:
    method: str
    scoring: str
    max_claims: int
    options: CallOptions

    @classmethod
    def parse(cls, kind: str, config: dict[str, Any], defaults: JudgeDefaults) -> JudgeConfig:
        allowed = _METHODS[kind]
        method = str(config.get("method") or _DEFAULT_METHOD[kind]).strip().lower()
        if method not in allowed:
            raise ValueError(
                f"{kind} judge: method must be one of {sorted(allowed)}, got {method!r}"
            )
        scoring = str(config.get("scoring") or "recall").strip().lower()
        if scoring not in _SCORINGS:
            raise ValueError(
                f"{kind} judge: scoring must be one of {sorted(_SCORINGS)}, got {scoring!r}"
            )
        max_claims = config.get("max_claims", DEFAULT_MAX_CLAIMS)
        if isinstance(max_claims, bool) or not isinstance(max_claims, int) or max_claims < 1:
            raise ValueError(f"{kind} judge: max_claims must be an integer >= 1")
        raw_model = config.get("model")
        model = str(raw_model).strip() if raw_model is not None else ""
        return cls(
            method=method,
            scoring=scoring,
            max_claims=max_claims,
            options=CallOptions(
                model=model or defaults.model,
                temperature=_parse_temperature(kind, config.get("temperature")),
            ),
        )


def _parse_temperature(kind: str, value: Any) -> float | None:
    if value is None:
        return None
    invalid = ValueError(f"{kind} judge: temperature must be a finite number, got {value!r}")
    if isinstance(value, bool):
        raise invalid
    try:
        temperature = float(value)
    except (TypeError, ValueError):
        raise invalid from None
    if not math.isfinite(temperature):
        raise invalid
    return temperature


def _documents(context: Any) -> list[dict[str, Any]]:
    if not isinstance(context, dict):
        return []
    documents = context.get("documents")
    if not isinstance(documents, list):
        return []
    return [d for d in documents if isinstance(d, dict)]


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "…"


def _cap(text: str, limit: int = _EXPLANATION_LIMIT) -> str:
    """Bound an explanation (stored in a String(4000) column), keeping its head."""
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _quote_list(items: list[str]) -> str:
    shown = "; ".join(f'"{_clip(text, _QUOTED_CLAIM_CHARS)}"' for text in items[:_QUOTED_CLAIMS])
    extra = len(items) - _QUOTED_CLAIMS
    return shown + (f" (+{extra} more)" if extra > 0 else "")


def _with_lists(head: str, records: list[dict[str, Any]], verdicts: tuple[str, ...]) -> str:
    parts = [head]
    for verdict in verdicts:
        texts = [r["text"] for r in records if r["verdict"] == verdict]
        if texts:
            parts.append(f"{verdict.replace('_', ' ')}: {_quote_list(texts)}")
    return "; ".join(parts)


class _LlmJudge:
    kind: str

    def __init__(
        self,
        config: dict[str, Any],
        llm: LlmClient,
        *,
        defaults: JudgeDefaults,
        claim_cache: JudgeClaimCacheRepository | None = None,
    ) -> None:
        self._config = JudgeConfig.parse(self.kind, config, defaults)
        self._llm = llm
        self._cache = claim_cache
        self.name = self.kind
        self.prompt_version = prompts.prompt_version(self.kind, self._config.method)

    async def evaluate(self, sample: EvaluationSample) -> EvaluationResult:
        early = self._precheck(sample)
        if early is not None:
            return early
        try:
            return await self._evaluate(sample)
        except JudgeOutputError as exc:
            return error(
                f"judge output invalid after repair: {exc}",
                error_type=JUDGE_OUTPUT_INVALID,
                metadata=self._meta(raw_output=exc.raw[:_RAW_OUTPUT_LIMIT]),
            )
        except Exception as exc:  # noqa: BLE001 — provider failures become ERROR results
            return error(
                f"{type(exc).__name__}: {exc}"[:2000],
                error_type=classify_llm_error(exc),
                metadata=self._meta(),
            )

    def _precheck(self, sample: EvaluationSample) -> EvaluationResult | None:
        if sample.actual_output is None:
            return skip("actual_output is missing", metadata=self._meta())
        return None

    async def _evaluate(self, sample: EvaluationSample) -> EvaluationResult:
        raise NotImplementedError

    def _meta(self, **extra: Any) -> dict[str, Any]:
        return {
            "judge_kind": self.kind,
            "method": self._config.method,
            "prompt_version": self.prompt_version,
            "model": self._config.options.model,
            **extra,
        }

    async def _rubric(self, user: str) -> EvaluationResult:
        out, calls = await rubric_judge(
            self._llm, system=prompts.RUBRICS[self.kind], user=user, options=self._config.options
        )
        reasoning = (out.reasoning or "").strip()
        explanation = f"level {out.level}/5" + (f": {reasoning}" if reasoning else "")
        return EvaluationResult(
            score=level_to_score(out.level),
            label=None,
            explanation=explanation[:_EXPLANATION_LIMIT],
            metadata=self._meta(level=out.level, reasoning=reasoning, llm_calls=calls),
        )

    async def _extract(self, system: str, user: str) -> tuple[ExtractedClaims, list[str], bool]:
        extracted = await extract_claims(
            self._llm, system=system, user=user, options=self._config.options
        )
        claims, truncated = limit_claims(extracted.claims, self._config.max_claims)
        return extracted, claims, truncated


class GroundednessJudge(_LlmJudge):
    kind = "groundedness"

    def _precheck(self, sample: EvaluationSample) -> EvaluationResult | None:
        early = super()._precheck(sample)
        if early is not None:
            return early
        if sample.context is None:
            return skip("context is missing", metadata=self._meta())
        if not _documents(sample.context):
            return fail_min("context.documents are missing or empty", metadata=self._meta())
        return None

    async def _evaluate(self, sample: EvaluationSample) -> EvaluationResult:
        question = prompts.as_text(sample.input)
        answer = prompts.as_text(sample.actual_output)
        documents = prompts.render_documents(_documents(sample.context))
        if self._config.method == "rubric":
            return await self._rubric(
                prompts.sections(question=question, documents=documents, answer=answer)
            )

        extracted, claims, truncated = await self._extract(
            prompts.EXTRACT_ANSWER_CLAIMS, prompts.sections(question=question, answer=answer)
        )
        if not claims:
            return skip(
                "no_factual_claims: the answer makes no factual claims to verify",
                metadata=self._meta(n_claims=0, llm_calls=extracted.calls),
            )
        verdicts, verify_calls = await verify_support(
            self._llm,
            system=prompts.VERIFY_AGAINST_DOCUMENTS,
            user=prompts.sections(documents=documents, claims=prompts.render_claims(claims)),
            n=len(claims),
            options=self._config.options,
        )
        support = score_support(verdicts)
        records = support_claim_records(claims, verdicts)
        return EvaluationResult(
            score=support.score,
            label=None,
            explanation=_cap(
                _with_lists(
                    f"{support.n_supported}/{support.n_claims} claims supported",
                    records,
                    ("contradicted", "not_supported"),
                )
            ),
            metadata=self._meta(
                claims=records,
                n_claims=support.n_claims,
                n_supported=support.n_supported,
                n_contradicted=support.n_contradicted,
                claims_truncated=truncated,
                llm_calls=extracted.calls + verify_calls,
            ),
        )


class CorrectnessJudge(_LlmJudge):
    kind = "correctness"

    def _precheck(self, sample: EvaluationSample) -> EvaluationResult | None:
        early = super()._precheck(sample)
        if early is not None:
            return early
        if sample.expected_output is None:
            return skip("expected_output is missing", metadata=self._meta())
        return None

    async def _evaluate(self, sample: EvaluationSample) -> EvaluationResult:
        question = prompts.as_text(sample.input)
        answer = prompts.as_text(sample.actual_output)
        reference = prompts.as_text(sample.expected_output)
        if self._config.method == "rubric":
            return await self._rubric(
                prompts.sections(question=question, reference_answer=reference, answer=answer)
            )

        gold = await self._reference_claims(sample, question, reference)
        gold_claims, truncated = limit_claims(gold.claims, self._config.max_claims)
        if not gold_claims:
            return skip(
                "no_gold_claims: the expected output has no factual claims",
                metadata=self._meta(n_gold=0, llm_calls=gold.calls, cache_hit=gold.cache_hit),
            )
        verdicts, coverage_calls = await verify_coverage(
            self._llm,
            system=prompts.VERIFY_REFERENCE_COVERAGE,
            user=prompts.sections(
                question=question,
                reference_claims=prompts.render_claims(gold_claims),
                answer=answer,
            ),
            n=len(gold_claims),
            options=self._config.options,
        )
        coverage = score_coverage(verdicts)
        records = coverage_claim_records(gold_claims, verdicts)
        calls = gold.calls + coverage_calls
        score = coverage.score
        explanation = _with_lists(
            f"{coverage.n_covered}/{coverage.n_gold} reference facts covered",
            records,
            ("contradicted", "missing"),
        )
        suffix = ""
        extra: dict[str, Any] = {}

        if self._config.scoring == "f1":
            extracted, answer_claims, answer_truncated = await self._extract(
                prompts.EXTRACT_ANSWER_CLAIMS, prompts.sections(question=question, answer=answer)
            )
            calls += extracted.calls
            truncated = truncated or answer_truncated
            precision = 0.0
            answer_contradictions = 0
            if answer_claims:
                support_verdicts, support_calls = await verify_support(
                    self._llm,
                    system=prompts.VERIFY_AGAINST_REFERENCE,
                    user=prompts.sections(
                        reference_answer=reference, claims=prompts.render_claims(answer_claims)
                    ),
                    n=len(answer_claims),
                    options=self._config.options,
                )
                calls += support_calls
                support = score_support(support_verdicts)
                precision = support.score
                answer_contradictions = support.n_contradicted
                extra["answer_claims"] = support_claim_records(answer_claims, support_verdicts)
            contradicted = coverage.n_contradicted or answer_contradictions
            score = 0.0 if contradicted else f1(precision, coverage.recall)
            extra["precision"] = precision
            suffix = f"; precision {precision:.2f}, F1 {score:.2f}"
            if not answer_claims:
                suffix += "; answer has no claims"

        return EvaluationResult(
            score=score,
            label=None,
            # Cap the claim lists first so the F1 summary is never cut off.
            explanation=_cap(explanation, _EXPLANATION_LIMIT - len(suffix)) + suffix,
            metadata=self._meta(
                claims=records,
                n_gold=coverage.n_gold,
                n_covered=coverage.n_covered,
                n_contradicted=coverage.n_contradicted,
                n_missing=coverage.n_missing,
                recall=coverage.recall,
                scoring=self._config.scoring,
                cache_hit=gold.cache_hit,
                claims_truncated=truncated,
                llm_calls=calls,
                **extra,
            ),
        )

    async def _reference_claims(
        self, sample: EvaluationSample, question: str, reference: str
    ) -> ExtractedClaims:
        model = self._config.options.model or ""
        key = claim_cache_key(
            [sample.input, sample.expected_output], prompt_version=self.prompt_version, model=model
        )
        if self._cache is not None:
            cached = await self._cache.get(key)
            if cached is not None:
                return ExtractedClaims(claims=cached, calls=0, cache_hit=True)
        extracted = await extract_claims(
            self._llm,
            system=prompts.EXTRACT_REFERENCE_CLAIMS,
            user=prompts.sections(question=question, reference_answer=reference),
            options=self._config.options,
        )
        # Only validated output reaches this point, so a bad reply is never cached.
        if self._cache is not None:
            await self._cache.put(
                key, prompt_version=self.prompt_version, model=model, claims=extracted.claims
            )
            # Writes are first-wins: a concurrent run may have stored different claims.
            # Re-read so every run is judged against the same gold; keep ours if the
            # re-read finds nothing (e.g. cache errors are treated as a miss).
            stored = await self._cache.get(key)
            if stored:
                return ExtractedClaims(claims=stored, calls=extracted.calls, cache_hit=False)
        return extracted


class AnswerRelevanceJudge(_LlmJudge):
    kind = "answer_relevance"

    async def _evaluate(self, sample: EvaluationSample) -> EvaluationResult:
        return await self._rubric(
            prompts.sections(
                question=prompts.as_text(sample.input),
                answer=prompts.as_text(sample.actual_output),
            )
        )


class ContextPrecisionJudge(_LlmJudge):
    kind = "context_precision"

    def __init__(
        self,
        config: dict[str, Any],
        llm: LlmClient,
        *,
        defaults: JudgeDefaults,
        claim_cache: JudgeClaimCacheRepository | None = None,
    ) -> None:
        super().__init__(config, llm, defaults=defaults, claim_cache=claim_cache)
        raw_k = config.get("k")
        if raw_k is None:
            self._k: int | None = None
        else:
            if isinstance(raw_k, bool):
                raise ValueError(f"{self.kind} judge: k must be an integer >= 1")
            try:
                k_int = int(raw_k)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{self.kind} judge: k must be an integer >= 1") from exc
            if k_int < 1:
                raise ValueError(f"{self.kind} judge: k must be an integer >= 1")
            self._k = k_int

    def _precheck(self, sample: EvaluationSample) -> EvaluationResult | None:
        early = super()._precheck(sample)
        if early is not None:
            return early
        if sample.expected_output is None:
            return skip("expected_output is missing", metadata=self._meta())
        if sample.context is None:
            return skip("context is missing", metadata=self._meta())
        if not _documents(sample.context):
            return fail_min("context.documents are missing or empty", metadata=self._meta())
        return None

    def _select_documents(self, sample: EvaluationSample) -> tuple[list[dict[str, Any]], bool]:
        documents = _documents(sample.context)
        limit = self._config.max_claims
        if self._k is not None:
            limit = min(limit, self._k)
        truncated = len(documents) > limit
        return documents[:limit], truncated

    async def _evaluate(self, sample: EvaluationSample) -> EvaluationResult:
        question = prompts.as_text(sample.input)
        reference = prompts.as_text(sample.expected_output)
        documents, truncated = self._select_documents(sample)
        if self._config.method == "rubric":
            result = await self._rubric(
                prompts.sections(
                    question=question,
                    reference_answer=reference,
                    documents=prompts.render_documents(documents),
                )
            )
            if not truncated:
                return result
            return EvaluationResult(
                score=result.score,
                label=result.label,
                explanation=result.explanation,
                metadata={**result.metadata, "documents_truncated": True},
            )

        verdicts, calls = await verify_relevance(
            self._llm,
            system=prompts.VERIFY_CONTEXT_RELEVANCE,
            user=prompts.sections(
                question=question,
                reference_answer=reference,
                documents=prompts.render_numbered_documents(documents),
            ),
            n=len(documents),
            options=self._config.options,
        )
        relevances = [v.verdict == "relevant" for v in verdicts]
        score = average_precision(relevances)
        n_relevant = sum(relevances)
        records = [
            {
                "doc_id": str(doc.get("id", "?")) if isinstance(doc, dict) else "?",
                "verdict": v.verdict,
                "reasoning": v.reasoning,
            }
            for doc, v in zip(documents, verdicts, strict=True)
        ]
        return EvaluationResult(
            score=score,
            label=None,
            explanation=_cap(
                f"context precision {score:.3f} ({n_relevant}/{len(documents)} relevant)"
            ),
            metadata=self._meta(
                documents=records,
                n_documents=len(documents),
                n_relevant=n_relevant,
                documents_truncated=truncated,
                llm_calls=calls,
            ),
        )


_JUDGES: dict[str, type[_LlmJudge]] = {
    cls.kind: cls
    for cls in (GroundednessJudge, CorrectnessJudge, AnswerRelevanceJudge, ContextPrecisionJudge)
}


def create_llm_judge(
    kind: str,
    config: dict[str, Any],
    llm: LlmClient,
    *,
    defaults: JudgeDefaults,
    claim_cache: JudgeClaimCacheRepository | None = None,
) -> _LlmJudge:
    cls = _JUDGES.get(kind)
    if cls is None:
        raise ValueError(f"Unknown LLM judge kind: {kind}")
    return cls(config, llm, defaults=defaults, claim_cache=claim_cache)
