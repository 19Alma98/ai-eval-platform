"""RAG answer checks: citation accuracy and correct refusal (abstention).

``citation_accuracy``: the answer's citation markers are parsed locally (no LLM); each cited
statement is then verified by the judge against the documents it cites, and only those.
A citation to a source that was not retrieved fails the statement without an LLM call.

``refusal``: did the assistant decline exactly when it should? Whether the question is
answerable comes from the dataset item (``metadata.answerable`` / ``metadata.expected_refusal``),
from the reference answer (a reference that declines means "should refuse"), or, without gold,
from the retrieved documents (the judge decides whether they contain the answer).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from opengrade_server.domain.rag_qa import label_answerable
from opengrade_server.domain.repositories import JudgeClaimCacheRepository
from opengrade_server.evaluation.judges import prompts
from opengrade_server.evaluation.judges.claims import verify_support
from opengrade_server.evaluation.judges.evaluators import (
    JudgeDefaults,
    _cap,
    _documents,
    _LlmJudge,
    _with_lists,
)
from opengrade_server.evaluation.judges.parsing import call_structured
from opengrade_server.evaluation.judges.schemas import RefusalOut
from opengrade_server.evaluation.outcomes import fail_min, pass_, skip
from opengrade_server.evaluation.protocol import EvaluationResult, EvaluationSample, LlmClient

# --- citation parsing -------------------------------------------------------------------

# "[pto]", "[1]", "[1, 3]", "[^2]"; not markdown links "[text](url)".
DEFAULT_CITATION_PATTERN = r"\[([^\[\]\n]{1,200})\](?!\()"
_ID_SEPARATORS = re.compile(r"\s*[,;]\s*")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")
_DECORATION = re.compile(r"[*_#`>]")
_REFERENCE_HEADER = re.compile(
    r"^(?:sources?|references?|citations?|bibliography|fonti|riferimenti)$", re.IGNORECASE
)
_WORDS = re.compile(r"\w", re.UNICODE)
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([.,;:!?])")
_INVALID = "invalid_citation"


@dataclass(frozen=True, slots=True)
class CitedSegment:
    text: str
    citations: tuple[str, ...]


def _tokens(match: re.Match[str]) -> list[str]:
    raw = match.group(1) if match.re.groups else match.group(0)
    out: list[str] = []
    for part in _ID_SEPARATORS.split(raw or ""):
        token = part.strip().lstrip("^").strip()
        if token.lower().startswith("doc:"):
            token = token[4:].strip()
        if token:
            out.append(token)
    return out


def _dedupe(items: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(items))


def _leading_citations(part: str, pattern: re.Pattern[str]) -> tuple[list[str], str]:
    """Citation markers at the start of ``part`` ("[pto] Next sentence…") and the rest."""
    tokens: list[str] = []
    pos = 0
    while True:
        while pos < len(part) and (part[pos].isspace() or part[pos] in ",;"):
            pos += 1
        match = pattern.match(part, pos)
        if match is None or match.end() == pos:
            break
        tokens.extend(_tokens(match))
        pos = match.end()
    return tokens, part[pos:] if tokens else part


def split_cited_segments(answer: str, pattern: re.Pattern[str]) -> list[CitedSegment]:
    """Split an answer into sentences with the citations each one carries.

    A citation placed after the sentence's full stop ("… 20 days. [pto]") belongs to that
    sentence. Lines after a "Sources:" / "References:" header are a reference list, not
    statements, and are ignored. Segments with no words (only markers) are dropped.
    """
    segments: list[tuple[str, list[str]]] = []
    for line in answer.splitlines():
        line = _BULLET.sub("", line.strip())
        if not line:
            continue
        header = _DECORATION.sub("", pattern.sub("", line)).strip(" \t:,;.-")
        if _REFERENCE_HEADER.match(header):
            break
        for part in _SENTENCE_END.split(line):
            leading, rest = _leading_citations(part, pattern)
            if leading and segments:
                segments[-1][1].extend(leading)
                leading = []
            cites = leading + [t for m in pattern.finditer(rest) for t in _tokens(m)]
            text = _SPACE_BEFORE_PUNCT.sub(r"\1", " ".join(pattern.sub("", rest).split()))
            if _WORDS.search(text):
                segments.append((text, cites))
            elif cites and segments:
                segments[-1][1].extend(cites)
    return [CitedSegment(text=t, citations=_dedupe(c)) for t, c in segments]


def _document_lookup(documents: list[dict[str, Any]]) -> dict[str, int]:
    """Citation key → document index: ids first, then titles."""
    lookup: dict[str, int] = {}
    for field in ("title", "id"):  # ids written last so they win over titles
        for i, doc in enumerate(documents):
            value = doc.get(field)
            if value is not None and str(value).strip():
                lookup[str(value).strip().casefold()] = i
    return lookup


def resolve_citation(
    token: str, documents: list[dict[str, Any]], lookup: dict[str, int]
) -> int | None:
    """Index of the cited document: by id, by title, else a 1-based position ("[2]")."""
    index = lookup.get(token.casefold())
    if index is not None:
        return index
    if token.isdigit() and 1 <= int(token) <= len(documents):
        return int(token) - 1
    return None


# --- refusal phrases ----------------------------------------------------------------------

DEFAULT_REFUSAL_PHRASES: tuple[str, ...] = (
    # English
    "i don't know",
    "i do not know",
    "i'm not sure",
    "i am not sure",
    "i cannot answer",
    "i can't answer",
    "i'm unable to",
    "i am unable to",
    "i don't have information",
    "i do not have information",
    "i don't have enough information",
    "i do not have enough information",
    "no information about",
    "not mentioned in",
    "not covered in",
    "not in the documents",
    "not in the provided",
    "not available in",
    "the documents do not",
    "the context does not",
    "cannot find",
    "can't find",
    "could not find",
    "couldn't find",
    "unable to find",
    # Italian
    "non lo so",
    "non so",
    "non ho informazioni",
    "non ho abbastanza informazioni",
    "non dispongo di informazioni",
    "non è presente nei documenti",
    "non è indicato",
    "non è specificato",
    "non trovo",
    "non riesco a trovare",
    "non posso rispondere",
    "non sono in grado di rispondere",
    "nei documenti non",
)


def _normalize(text: str) -> str:
    return " ".join(text.replace("’", "'").replace("‘", "'").casefold().split())


def phrase_matcher(phrases: tuple[str, ...]) -> re.Pattern[str]:
    alternatives = "|".join(re.escape(_normalize(p)) for p in phrases)
    return re.compile(rf"(?<!\w)(?:{alternatives})(?!\w)")


_DEFAULT_REFUSAL_MATCHER = phrase_matcher(DEFAULT_REFUSAL_PHRASES)


def looks_like_refusal(text: str, matcher: re.Pattern[str] = _DEFAULT_REFUSAL_MATCHER) -> bool:
    return matcher.search(_normalize(text)) is not None


# --- config helpers -----------------------------------------------------------------------


def _bool_config(kind: str, config: dict[str, Any], key: str, default: bool) -> bool:
    value = config.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"{kind} judge: {key} must be true or false")
    return value


def _choice_config(kind: str, config: dict[str, Any], key: str, choices: tuple[str, ...]) -> str:
    value = str(config.get(key) or choices[0]).strip().lower()
    if value not in choices:
        raise ValueError(f"{kind} judge: {key} must be one of {list(choices)}, got {value!r}")
    return value


# --- citation accuracy ----------------------------------------------------------------------


class CitationAccuracyJudge(_LlmJudge):
    """Share of cited statements that their cited sources actually support.

    Config: ``pattern`` (regex whose first group captures the cited id(s); default ``[id]``),
    ``require_citations`` (default true: an answer that cites nothing FAILs, unless it is a
    refusal), ``min_coverage`` (0-1, optional: FAIL when fewer sentences carry a citation),
    ``max_claims`` (statements verified), ``model``, ``temperature``.
    """

    kind = "citation_accuracy"

    def __init__(
        self,
        config: dict[str, Any],
        llm: LlmClient,
        *,
        defaults: JudgeDefaults,
        claim_cache: JudgeClaimCacheRepository | None = None,
    ) -> None:
        super().__init__(config, llm, defaults=defaults, claim_cache=claim_cache)
        raw_pattern = config.get("pattern") or DEFAULT_CITATION_PATTERN
        try:
            self._pattern = re.compile(str(raw_pattern))
        except re.error as exc:
            raise ValueError(f"{self.kind} judge: pattern is not a valid regex: {exc}") from exc
        self._custom_pattern = raw_pattern != DEFAULT_CITATION_PATTERN
        self._require = _bool_config(self.kind, config, "require_citations", True)
        min_coverage = config.get("min_coverage")
        if min_coverage is not None and (
            isinstance(min_coverage, bool)
            or not isinstance(min_coverage, int | float)
            or not 0 <= min_coverage <= 1
        ):
            raise ValueError(f"{self.kind} judge: min_coverage must be a number between 0 and 1")
        self._min_coverage = float(min_coverage) if min_coverage is not None else None

    def _meta(self, **extra: Any) -> dict[str, Any]:
        meta = super()._meta(**extra)
        if self._custom_pattern:
            meta["pattern"] = self._pattern.pattern
        return meta

    async def _evaluate(self, sample: EvaluationSample) -> EvaluationResult:
        answer = prompts.as_text(sample.actual_output)
        documents = _documents(sample.context)
        segments = split_cited_segments(answer, self._pattern)
        cited = [s for s in segments if s.citations]
        n_uncited = len(segments) - len(cited)
        coverage = len(cited) / len(segments) if segments else 0.0
        counts = {"n_sentences": len(segments), "n_uncited": n_uncited}

        if not cited:
            if looks_like_refusal(answer):
                return skip(
                    "the answer declines to answer, so there is nothing to cite",
                    metadata=self._meta(**counts, citation_coverage=0.0),
                )
            if self._require:
                return fail_min(
                    "the answer cites no sources",
                    metadata=self._meta(**counts, citation_coverage=0.0, llm_calls=0),
                )
            return skip(
                "the answer cites no sources (require_citations=false)",
                metadata=self._meta(**counts, citation_coverage=0.0),
            )

        truncated = len(cited) > self._config.max_claims
        cited = cited[: self._config.max_claims]
        lookup = _document_lookup(documents)
        resolved: list[tuple[CitedSegment, list[int], list[str]]] = []
        for segment in cited:
            indexes: list[int] = []
            invalid: list[str] = []
            for token in segment.citations:
                index = resolve_citation(token, documents, lookup)
                if index is None:
                    invalid.append(token)
                elif index not in indexes:
                    indexes.append(index)
            resolved.append((segment, indexes, invalid))

        to_verify = [(i, seg, idx) for i, (seg, idx, _) in enumerate(resolved) if idx]
        cited_docs = sorted({j for _, _, idx in to_verify for j in idx})
        if to_verify and not any(str(documents[j].get("text") or "").strip() for j in cited_docs):
            return skip(
                "cited documents have no text (only ids were stored, e.g. "
                "CONTENT_CAPTURE_ENABLED=false)",
                metadata=self._meta(**counts),
            )

        verdicts: dict[int, Any] = {}
        calls = 0
        if to_verify:
            claims = [
                f"{seg.text} (cites: "
                + ", ".join(str(documents[j].get("id", j + 1)) for j in idx)
                + ")"
                for _, seg, idx in to_verify
            ]
            results, calls = await verify_support(
                self._llm,
                system=prompts.VERIFY_CITATIONS,
                user=prompts.sections(
                    documents=prompts.render_documents([documents[j] for j in cited_docs]),
                    claims=prompts.render_claims(claims),
                ),
                n=len(claims),
                options=self._config.options,
            )
            verdicts = {i: v for (i, _, _), v in zip(to_verify, results, strict=True)}

        records: list[dict[str, Any]] = []
        for i, (segment, indexes, invalid) in enumerate(resolved):
            verdict = verdicts.get(i)
            doc_ids = [str(documents[j].get("id", j + 1)) for j in indexes]
            if invalid:
                records.append(
                    {
                        "text": segment.text,
                        "verdict": _INVALID,
                        "doc_ids": doc_ids,
                        "invalid_citations": invalid,
                        "quote": None,
                        "reasoning": "cites a source that was not retrieved: " + ", ".join(invalid),
                    }
                )
                continue
            records.append(
                {
                    "text": segment.text,
                    "verdict": verdict.verdict if verdict else "not_supported",
                    "doc_ids": doc_ids,
                    "quote": verdict.quote if verdict else None,
                    "reasoning": verdict.reasoning if verdict else None,
                }
            )

        n = len(records)
        n_supported = sum(r["verdict"] == "supported" for r in records)
        n_invalid = sum(r["verdict"] == _INVALID for r in records)
        n_contradicted = sum(r["verdict"] == "contradicted" for r in records)
        score = n_supported / n
        explanation = _with_lists(
            f"{n_supported}/{n} cited statements supported by their sources",
            records,
            ("contradicted", "not_supported", _INVALID),
        )
        suffix = f"; {n_uncited} sentence(s) without a citation" if n_uncited else ""
        label: str | None = None
        if self._min_coverage is not None and coverage < self._min_coverage:
            label = "FAIL"
            suffix += f"; citation coverage {coverage:.0%} < {self._min_coverage:.0%}"
        return EvaluationResult(
            score=score,
            label=label,
            explanation=_cap(explanation, 1000 - len(suffix)) + suffix,
            metadata=self._meta(
                claims=records,
                n_statements=n,
                n_supported=n_supported,
                n_contradicted=n_contradicted,
                n_invalid_citations=n_invalid,
                citation_coverage=round(coverage, 4),
                claims_truncated=truncated,
                llm_calls=calls,
                **counts,
            ),
        )


# --- refusal ---------------------------------------------------------------------------------

_ANSWERABLE_FROM = ("auto", "label", "documents")
_CHECKS = ("both", "unanswerable", "answerable")
_OUTCOMES = {
    (True, False): ("correct_answer", 1.0),
    (True, True): ("over_refusal", 0.0),
    (False, True): ("correct_refusal", 1.0),
    (False, False): ("missed_refusal", 0.0),
}
_OUTCOME_TEXT = {
    "correct_answer": "answered an answerable question",
    "over_refusal": "declined a question it should have answered",
    "correct_refusal": "correctly declined a question it cannot answer",
    "missed_refusal": "answered a question it should have declined (likely hallucination)",
}
_SOURCE_TEXT = {
    "label": "dataset label",
    "reference": "reference answer",
    "documents": "retrieved documents",
}


class RefusalJudge(_LlmJudge):
    """Did the assistant decline exactly when it should? Score 1 (right call) or 0.

    Config: ``method`` ("classify": LLM, default; "phrases": deterministic phrase match, no
    LLM call), ``refusal_phrases`` (phrases method; replaces the English/Italian defaults),
    ``answerable_from`` ("auto" default: dataset label, then reference answer, then documents;
    "label": only the label / reference; "documents": only the retrieved documents, classify
    method), ``check`` ("both" default; "unanswerable" scores only items that should be
    declined — missed refusals; "answerable" only the others — over-refusals).
    """

    kind = "refusal"
    requires_answer = True

    def __init__(
        self,
        config: dict[str, Any],
        llm: LlmClient,
        *,
        defaults: JudgeDefaults,
        claim_cache: JudgeClaimCacheRepository | None = None,
    ) -> None:
        super().__init__(config, llm, defaults=defaults, claim_cache=claim_cache)
        self._answerable_from = _choice_config(
            self.kind, config, "answerable_from", _ANSWERABLE_FROM
        )
        self._check = _choice_config(self.kind, config, "check", _CHECKS)
        if self._config.method == "phrases" and self._answerable_from == "documents":
            raise ValueError(
                f"{self.kind} judge: answerable_from='documents' needs method 'classify' "
                "(phrase matching cannot read documents)"
            )
        raw_phrases = config.get("refusal_phrases")
        if raw_phrases is None:
            self._matcher = _DEFAULT_REFUSAL_MATCHER
            self._custom_phrases = False
        else:
            if (
                not isinstance(raw_phrases, list)
                or not raw_phrases
                or not all(isinstance(p, str) and p.strip() for p in raw_phrases)
            ):
                raise ValueError(
                    f"{self.kind} judge: refusal_phrases must be a non-empty list of strings"
                )
            self._matcher = phrase_matcher(tuple(raw_phrases))
            self._custom_phrases = True

    def _meta(self, **extra: Any) -> dict[str, Any]:
        meta = super()._meta(**extra)
        if self._custom_phrases:
            meta["custom_phrases"] = True
        return meta

    def _source(self, sample: EvaluationSample) -> str | None:
        has_label = label_answerable(sample.metadata or {}) is not None
        has_reference = bool(prompts.as_text(sample.expected_output))
        has_documents = isinstance(sample.context, dict) and isinstance(
            sample.context.get("documents"), list
        )
        if self._answerable_from in ("auto", "label"):
            if has_label:
                return "label"
            if has_reference:
                return "reference"
        if self._answerable_from in ("auto", "documents") and self._config.method == "classify":
            if has_documents:
                return "documents"
        return None

    def _filtered(self, expected_answerable: bool) -> bool:
        return (self._check == "unanswerable" and expected_answerable) or (
            self._check == "answerable" and not expected_answerable
        )

    def _skip_filtered(self, meta: dict[str, Any]) -> EvaluationResult:
        which = "answerable" if meta["expected_answerable"] else "not answerable"
        return skip(
            f"question is {which}; this entry only scores check={self._check}",
            metadata=self._meta(**meta),
        )

    async def _evaluate(self, sample: EvaluationSample) -> EvaluationResult:
        source = self._source(sample)
        if source is None:
            hint = (
                "set metadata.answerable (or expected_output) on the dataset item"
                if self._answerable_from == "label"
                else "set metadata.answerable or expected_output, or record the retrieved "
                "documents"
                + (
                    " (the phrases method cannot read documents)"
                    if self._config.method == "phrases"
                    else ""
                )
            )
            return skip(
                f"cannot tell whether the question is answerable: {hint}", metadata=self._meta()
            )

        answer = prompts.as_text(sample.actual_output)
        reference = prompts.as_text(sample.expected_output)
        documents = _documents(sample.context)
        expected_answerable: bool | None = None
        if source == "label":
            expected_answerable = label_answerable(sample.metadata or {})
            assert expected_answerable is not None
            if self._filtered(expected_answerable):
                return self._skip_filtered(
                    {"answerable_source": source, "expected_answerable": expected_answerable}
                )
        elif source == "documents" and not documents:
            expected_answerable = False  # nothing retrieved: the assistant cannot know
        elif source == "documents" and not any(str(d.get("text") or "").strip() for d in documents):
            return skip(
                "retrieved documents have no text (only ids were stored, e.g. "
                "CONTENT_CAPTURE_ENABLED=false)",
                metadata=self._meta(answerable_source=source),
            )

        reasoning: str | None = None
        calls = 0
        if self._config.method == "phrases":
            refused = looks_like_refusal(answer, self._matcher)
            if source == "reference":
                expected_answerable = not looks_like_refusal(reference, self._matcher)
        else:
            with_reference = source == "reference"
            with_documents = source == "documents" and expected_answerable is None
            parts: dict[str, str] = {
                "question": prompts.question_text(sample.input),
                "answer": answer,
            }
            if with_reference:
                parts["reference_answer"] = reference
            if with_documents:
                parts["documents"] = prompts.render_documents(documents)

            def check(out: RefusalOut) -> None:
                if with_reference and out.reference_refused is None:
                    raise ValueError("reference_refused must be true or false")
                if with_documents and out.answerable_from_documents is None:
                    raise ValueError("answerable_from_documents must be true or false")

            result = await call_structured(
                self._llm,
                system=prompts.CLASSIFY_REFUSAL,
                user=prompts.sections(**parts),
                schema=RefusalOut,
                options=self._config.options,
                check=check,
            )
            calls = result.calls
            refused = result.value.answer_refused
            reasoning = (result.value.reasoning or "").strip() or None
            if with_reference:
                expected_answerable = not result.value.reference_refused
            elif with_documents:
                expected_answerable = bool(result.value.answerable_from_documents)

        assert expected_answerable is not None
        meta = {
            "answerable_source": source,
            "expected_answerable": expected_answerable,
            "refused": refused,
            "reasoning": reasoning,
            "llm_calls": calls,
        }
        if self._filtered(expected_answerable):
            return self._skip_filtered(meta)
        outcome, score = _OUTCOMES[(expected_answerable, refused)]
        explanation = (
            f"{outcome.replace('_', ' ')}: {_OUTCOME_TEXT[outcome]} ({_SOURCE_TEXT[source]})"
        )
        if reasoning:
            explanation += f"; {reasoning}"
        build = pass_ if score == 1.0 else fail_min
        return build(_cap(explanation), score=score, metadata=self._meta(outcome=outcome, **meta))


RAG_CHECK_JUDGES: dict[str, type[_LlmJudge]] = {
    CitationAccuracyJudge.kind: CitationAccuracyJudge,
    RefusalJudge.kind: RefusalJudge,
}
