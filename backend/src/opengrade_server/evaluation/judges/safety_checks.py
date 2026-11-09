"""RAG safety checks: ``pii``, ``toxicity`` and ``prompt_injection``.

Each kind is one structured LLM classify call over the configured ``fields`` (any of
``input``, ``output``, ``documents``). Score 1.0 / PASS when clean, 0.0 / FAIL when flagged.
None needs a reference answer, so all three also run on live traffic.

``prompt_injection`` never reads the assistant ``output``: the attack surface is what goes
into the model (user question, retrieved documents), and an answer that echoes an attack
would be scored as the attack.
"""

from __future__ import annotations

from typing import Any

from opengrade_server.domain.repositories import JudgeClaimCacheRepository
from opengrade_server.evaluation.judges import prompts
from opengrade_server.evaluation.judges.evaluators import (
    JudgeDefaults,
    _cap,
    _clip,
    _documents,
    _LlmJudge,
)
from opengrade_server.evaluation.judges.parsing import call_structured
from opengrade_server.evaluation.judges.schemas import SafetyClassifyOut
from opengrade_server.evaluation.outcomes import fail_min, pass_, skip
from opengrade_server.evaluation.protocol import EvaluationResult, EvaluationSample, LlmClient

SAFETY_FIELDS = ("input", "output", "documents")
MAX_EVIDENCE = 5
MAX_EVIDENCE_CHARS = 200
_OTHER = "other"
# Prompt section name for each field.
_SECTION = {"input": "question", "output": "answer", "documents": "documents"}


def parse_fields(
    kind: str,
    config: dict[str, Any],
    default: tuple[str, ...],
    forbidden: frozenset[str] = frozenset(),
) -> tuple[str, ...]:
    """Ordered, de-duplicated subset of ``SAFETY_FIELDS``; raises ``ValueError`` when invalid."""
    raw = config.get("fields")
    if raw is None:
        return default
    if not isinstance(raw, list) or not all(isinstance(f, str) for f in raw):
        raise ValueError(f"{kind} judge: fields must be a list of {list(SAFETY_FIELDS)}")
    fields = tuple(dict.fromkeys(f.strip().lower() for f in raw))
    if not fields:
        raise ValueError(f"{kind} judge: fields must not be empty")
    unknown = [f for f in fields if f not in SAFETY_FIELDS]
    if unknown:
        raise ValueError(
            f"{kind} judge: unknown field(s) {unknown}; allowed: {list(SAFETY_FIELDS)}"
        )
    blocked = [f for f in fields if f in forbidden]
    if blocked:
        raise ValueError(f"{kind} judge: field(s) {blocked} not allowed for this check")
    return fields


def _field_text(field: str, sample: EvaluationSample) -> str:
    """Rendered text of one field, or "" when it has no usable content."""
    if field == "input":
        if sample.input is None:
            return ""
        return prompts.question_text(sample.input).strip()
    if field == "output":
        return prompts.as_text(sample.actual_output)
    documents = [d for d in _documents(sample.context) if str(d.get("text") or "").strip()]
    return prompts.render_documents(documents) if documents else ""


def normalize_categories(raw: list[str], allowed: tuple[str, ...]) -> list[str]:
    out: list[str] = []
    for item in raw:
        category = item.strip().lower().replace("-", "_").replace(" ", "_")
        if category not in allowed:
            category = _OTHER
        if category not in out:
            out.append(category)
    return out


def cap_evidence(raw: list[str]) -> list[str]:
    return [_clip(" ".join(e.split()), MAX_EVIDENCE_CHARS) for e in raw[:MAX_EVIDENCE]]


class _SafetyJudge(_LlmJudge):
    """Base for the three safety classifiers. Subclasses set the kind-specific constants."""

    requires_answer = False
    default_fields: tuple[str, ...]
    forbidden_fields: frozenset[str] = frozenset()
    categories: tuple[str, ...]

    def __init__(
        self,
        config: dict[str, Any],
        llm: LlmClient,
        *,
        defaults: JudgeDefaults,
        claim_cache: JudgeClaimCacheRepository | None = None,
    ) -> None:
        super().__init__(config, llm, defaults=defaults, claim_cache=claim_cache)
        self._fields = parse_fields(self.kind, config, self.default_fields, self.forbidden_fields)

    async def _evaluate(self, sample: EvaluationSample) -> EvaluationResult:
        texts = {field: _field_text(field, sample) for field in self._fields}
        checked = [f for f in self._fields if texts[f]]
        missing = [f for f in self._fields if not texts[f]]
        if not checked:
            return skip(
                f"nothing to check: configured fields {list(self._fields)} are all empty"
                + (
                    " (documents without text are ignored, e.g. CONTENT_CAPTURE_ENABLED=false)"
                    if "documents" in self._fields
                    else ""
                ),
                metadata=self._meta(fields_checked=[], fields_missing=missing),
            )

        result = await call_structured(
            self._llm,
            system=prompts.SAFETY_CLASSIFIERS[self.kind],
            user=prompts.sections(**{_SECTION[f]: texts[f] for f in checked}),
            schema=SafetyClassifyOut,
            options=self._config.options,
        )
        out = result.value
        flagged = out.flagged
        categories = normalize_categories(out.categories, self.categories) if flagged else []
        if flagged and not categories:
            categories = [_OTHER]
        evidence = cap_evidence(out.evidence) if flagged else []
        reasoning = (out.reasoning or "").strip() or None
        meta = self._meta(
            flagged=flagged,
            categories=categories,
            evidence=evidence,
            fields_checked=checked,
            fields_missing=missing,
            reasoning=reasoning,
            llm_calls=result.calls,
        )
        if not flagged:
            return pass_(_cap(f"{self.kind}: clean"), score=1.0, metadata=meta)
        explanation = f"{self.kind}: flagged ({', '.join(categories)})"
        if evidence:
            explanation += "; " + "; ".join(f'"{e}"' for e in evidence)
        elif reasoning:
            explanation += f"; {reasoning}"
        return fail_min(_cap(explanation), score=0.0, metadata=meta)


class PiiJudge(_SafetyJudge):
    kind = "pii"
    default_fields = ("input", "output")
    categories = prompts.PII_CATEGORIES


class ToxicityJudge(_SafetyJudge):
    kind = "toxicity"
    default_fields = ("input", "output")
    categories = prompts.TOXICITY_CATEGORIES


class PromptInjectionJudge(_SafetyJudge):
    kind = "prompt_injection"
    default_fields = ("input", "documents")
    forbidden_fields = frozenset({"output"})
    categories = prompts.PROMPT_INJECTION_CATEGORIES


SAFETY_CHECK_JUDGES: dict[str, type[_LlmJudge]] = {
    cls.kind: cls for cls in (PiiJudge, ToxicityJudge, PromptInjectionJudge)
}
