"""All LLM judge prompt text.

`prompt_version` is a content hash of the system templates used by each
(kind, method) pair so runs scored with different prompts are not comparable.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

STEP_PREFIX = "STEP: "
_SHORT_HASH_LEN = 12


def _system(step: str, body: str) -> str:
    return f"{STEP_PREFIX}{step}\n{body.strip()}"


def _section(title: str, body: str) -> str:
    return f"# {title}\n{body.strip()}"


def _compose(*sections: str) -> str:
    return "\n\n".join(s.strip() for s in sections if s and s.strip())


def _bullets(*items: str) -> str:
    return "\n".join(f"- {item}" for item in items)


def _numbered(*items: str) -> str:
    return "\n".join(f"{i}. {item}" for i, item in enumerate(items, 1))


_VERIFY_LENGTH_RULE = (
    'If there are N labeled items, "verdicts" must be a JSON array of length exactly N, '
    "in the same order (index 0 = first label). Include a verdict for every item, "
    "including unsupported or missing facts."
)

_EXTRACT_RULES = _bullets(
    "One fact per claim. Split compound sentences and unrelated facts into separate claims.",
    "Make each claim self-contained: replace pronouns using the QUESTION for context.",
    "Keep original wording, numbers, dates, and names. Do not add, infer, or correct facts.",
    "Skip non-factual text (greetings, apologies, offers of help, restating the question).",
    'If there are no factual claims (refusal, "I don\'t know"), return an empty list.',
)

_EXTRACT_EXAMPLES = """\
### Example 1 — split compound facts
Input answer: "Full-time employees get 20 PTO days and free downtown parking."
Output:
```json
{"claims": [
  "Full-time employees get 20 PTO days.",
  "Full-time employees get free downtown parking."
]}
```

### Example 2 — no factual content
Input answer: "I'm not sure I can help with that."
Output:
```json
{"claims": []}
```"""

_EXTRACT_OUTPUT = (
    'Respond with JSON only: {"claims": ["<claim>", ...]}\nNo prose outside the JSON object.'
)

_EXTRACT_STEPS = _numbered(
    "Read the QUESTION for context (pronouns, entities).",
    "Scan the source text for atomic factual statements.",
    "Emit the claims list (or empty) as JSON.",
)


def _extract_body(*, source: str) -> str:
    return _compose(
        _section(
            "Role",
            "You are an evaluation assistant that decomposes text into atomic claims.",
        ),
        _section("Task", f"Break the {source} into atomic factual claims."),
        _section("Steps", _EXTRACT_STEPS),
        _section("Rules", _EXTRACT_RULES),
        _section("Examples", _EXTRACT_EXAMPLES),
        _section("Output", _EXTRACT_OUTPUT),
    )


def _verify_output(schema_line: str) -> str:
    return (
        f"Respond with JSON only: {schema_line}\n"
        'Put "reasoning" before "verdict" in each object. No prose outside the JSON object.'
    )


EXTRACT_ANSWER_CLAIMS = _system("extract_answer_claims", _extract_body(source="ANSWER"))

EXTRACT_REFERENCE_CLAIMS = _system(
    "extract_reference_claims", _extract_body(source="REFERENCE ANSWER")
)

VERIFY_AGAINST_DOCUMENTS = _system(
    "verify_against_documents",
    _compose(
        _section("Role", "You are an evaluation judge for document-grounded claim support."),
        _section(
            "Task",
            "For each CLAIM ([C1], [C2], …), decide whether the DOCUMENTS support it.",
        ),
        _section(
            "Steps",
            _numbered(
                "Read the documents, then each claim in order.",
                "Decide support using only the documents (no outside knowledge).",
                "For each claim, note short reasoning, verdict, doc ids, and a short quote.",
                'Emit one object per claim in "verdicts", same order and length.',
            ),
        ),
        _section(
            "Rules",
            _bullets(
                _VERIFY_LENGTH_RULE,
                "Use only the documents; never outside knowledge.",
                "Judge each claim independently, including claims the documents never mention.",
                'List relied-on document ids in "doc_ids"; copy the shortest supporting or '
                'contradicting passage into "quote" (null if none).',
                "Keep reasoning short.",
            ),
        ),
        _section(
            "Labels",
            _bullets(
                '"supported": the documents state it, or it follows directly from them.',
                '"contradicted": the documents state something incompatible with it.',
                '"not_supported": the documents do not mention it, or support it only partially.',
            ),
        ),
        _section(
            "Examples",
            """\
### Example 1 — mixed support (N=2)
Claims: [C1] Full-time employees get 20 PTO days. [C2] Parking is free downtown.
Documents mention 20 PTO days; parking is absent.
Output:
```json
{"verdicts": [
  {"reasoning": "stated in doc", "verdict": "supported",
   "doc_ids": ["pto"], "quote": "20 days"},
  {"reasoning": "not in docs", "verdict": "not_supported",
   "doc_ids": [], "quote": null}
]}
```

### Example 2 — contradiction
Claim conflicts with a document fact → verdict "contradicted" with a short quote.""",
        ),
        _section(
            "Output",
            _verify_output(
                '{"verdicts": [{"reasoning": "<why>", "verdict": "supported" | '
                '"contradicted" | "not_supported", "doc_ids": ["<id>"], '
                '"quote": "<passage>" | null}, ...]}'
            ),
        ),
    ),
)

VERIFY_AGAINST_REFERENCE = _system(
    "verify_against_reference",
    _compose(
        _section("Role", "You are an evaluation judge for reference-grounded claim support."),
        _section(
            "Task",
            "For each CLAIM ([C1], [C2], …) from an answer, decide whether the "
            "REFERENCE ANSWER supports it.",
        ),
        _section(
            "Steps",
            _numbered(
                "Read the reference answer, then each claim in order.",
                "Decide support using only the reference (no outside knowledge).",
                'Emit one object per claim in "verdicts", same order and length.',
            ),
        ),
        _section(
            "Rules",
            _bullets(
                _VERIFY_LENGTH_RULE,
                "Use only the reference answer; never outside knowledge.",
                "Keep reasoning short.",
            ),
        ),
        _section(
            "Labels",
            _bullets(
                '"supported": the reference states it, or it follows directly from it.',
                '"contradicted": the reference states something incompatible with it.',
                '"not_supported": the reference does not mention it.',
            ),
        ),
        _section(
            "Examples",
            """\
### Example 1 — mixed support (N=2)
Output:
```json
{"verdicts": [
  {"reasoning": "matches reference", "verdict": "supported"},
  {"reasoning": "extra detail absent from reference", "verdict": "not_supported"}
]}
```

### Example 2 — contradiction
Claim conflicts with the reference → verdict "contradicted".""",
        ),
        _section(
            "Output",
            _verify_output(
                '{"verdicts": [{"reasoning": "<why>", "verdict": "supported" | '
                '"contradicted" | "not_supported"}, ...]}'
            ),
        ),
    ),
)

VERIFY_REFERENCE_COVERAGE = _system(
    "verify_reference_coverage",
    _compose(
        _section("Role", "You are an evaluation judge for answer coverage of gold claims."),
        _section(
            "Task",
            "For each REFERENCE CLAIM ([C1], [C2], …), decide whether the ANSWER conveys it.",
        ),
        _section(
            "Steps",
            _numbered(
                "Read the answer, then each reference claim in order.",
                "Decide whether the answer covers, contradicts, or omits that fact.",
                'Emit one object per claim in "verdicts", same order and length.',
            ),
        ),
        _section(
            "Rules",
            _bullets(
                _VERIFY_LENGTH_RULE,
                "Wording may differ; numbers, dates, names, and conditions must match.",
                "Extra information in the answer is not your concern.",
                "Keep reasoning short.",
            ),
        ),
        _section(
            "Labels",
            _bullets(
                '"covered": the answer states the same fact.',
                '"contradicted": the answer states something incompatible with it.',
                '"missing": the answer does not state it.',
            ),
        ),
        _section(
            "Examples",
            """\
### Example 1 — mixed coverage (N=2)
Output:
```json
{"verdicts": [
  {"reasoning": "answer states the same fact", "verdict": "covered"},
  {"reasoning": "answer omits this fact", "verdict": "missing"}
]}
```

### Example 2 — contradiction
Answer asserts an incompatible value → verdict "contradicted".""",
        ),
        _section(
            "Output",
            _verify_output(
                '{"verdicts": [{"reasoning": "<why>", "verdict": "covered" | '
                '"contradicted" | "missing"}, ...]}'
            ),
        ),
    ),
)

VERIFY_CONTEXT_RELEVANCE = _system(
    "verify_context_relevance",
    _compose(
        _section("Role", "You are an evaluation judge for retrieval relevance."),
        _section(
            "Task",
            "For each DOCUMENT ([D1], [D2], …), decide whether it is useful for producing "
            "the REFERENCE ANSWER to the QUESTION.",
        ),
        _section(
            "Steps",
            _numbered(
                "Read the question and reference answer.",
                "For each document in order, decide if it helps produce that reference.",
                'Emit one object per document in "verdicts", same order and length.',
            ),
        ),
        _section(
            "Rules",
            _bullets(
                _VERIFY_LENGTH_RULE,
                "Use only the question, reference answer, and documents.",
                "Judge each document independently.",
                "Keep reasoning short.",
            ),
        ),
        _section(
            "Labels",
            _bullets(
                '"relevant": the document contains information needed for the reference answer '
                "(facts, conditions, or details the reference relies on).",
                '"not_relevant": the document is off-topic, redundant noise, or does not help '
                "produce the reference answer.",
            ),
        ),
        _section(
            "Examples",
            """\
### Example 1 — mixed relevance (N=2)
Output:
```json
{"verdicts": [
  {"reasoning": "contains the needed policy fact", "verdict": "relevant"},
  {"reasoning": "unrelated topic", "verdict": "not_relevant"}
]}
```

### Example 2 — noise
Document is on-topic for the company but unused by the reference → "not_relevant".""",
        ),
        _section(
            "Output",
            _verify_output(
                '{"verdicts": [{"reasoning": "<why>", "verdict": "relevant" | '
                '"not_relevant"}, ...]}'
            ),
        ),
    ),
)

VERIFY_CONTEXT_COVERAGE = _system(
    "verify_context_coverage",
    _compose(
        _section("Role", "You are an evaluation judge for context recall."),
        _section(
            "Task",
            "For each REFERENCE CLAIM ([C1], [C2], …), decide whether the DOCUMENTS convey it.",
        ),
        _section(
            "Steps",
            _numbered(
                "Read the documents, then each reference claim in order.",
                "Decide whether the documents cover, contradict, or omit that fact.",
                'Emit one object per claim in "verdicts", same order and length.',
            ),
        ),
        _section(
            "Rules",
            _bullets(
                _VERIFY_LENGTH_RULE,
                "Use only the documents; never outside knowledge.",
                "Wording may differ; numbers, dates, names, and conditions must match.",
                "Extra information in the documents is not your concern.",
                "Keep reasoning short.",
            ),
        ),
        _section(
            "Labels",
            _bullets(
                '"covered": the documents state the same fact.',
                '"contradicted": the documents state something incompatible with it.',
                '"missing": the documents do not state it.',
            ),
        ),
        _section(
            "Examples",
            """\
### Example 1 — mixed coverage (N=2)
Output:
```json
{"verdicts": [
  {"reasoning": "fact appears in retrieved docs", "verdict": "covered"},
  {"reasoning": "docs do not mention it", "verdict": "missing"}
]}
```

### Example 2 — contradiction
Documents assert an incompatible value → verdict "contradicted".""",
        ),
        _section(
            "Output",
            _verify_output(
                '{"verdicts": [{"reasoning": "<why>", "verdict": "covered" | '
                '"contradicted" | "missing"}, ...]}'
            ),
        ),
    ),
)


_RUBRIC_OUTPUT = (
    'Respond with JSON only: {"reasoning": "<why>", "level": <1-5>}\n'
    'Put "reasoning" before "level". No prose outside the JSON object.'
)

_RUBRIC_STEPS = _numbered(
    "Read only the fields relevant to this rubric.",
    "Write short reasoning that justifies the score.",
    "Choose the single best level from 1 to 5.",
    "Emit the JSON object.",
)


def _rubric(
    *,
    step: str,
    role: str,
    task: str,
    rules: str,
    scale: str,
    example_reasoning: str,
    example_level: int,
) -> str:
    examples = f"""\
### Example
```json
{{"reasoning": "{example_reasoning}", "level": {example_level}}}
```"""
    body = _compose(
        _section("Role", role),
        _section("Task", task),
        _section("Steps", _RUBRIC_STEPS),
        _section("Rules", rules),
        _section("Scale", scale),
        _section("Examples", examples),
        _section("Output", _RUBRIC_OUTPUT),
    )
    return _system(step, body)


RUBRICS: dict[str, str] = {
    "answer_relevance": _rubric(
        step="rubric_answer_relevance",
        role="You are an evaluation judge for answer relevance.",
        task=(
            "Rate how relevant the ANSWER is to the QUESTION. "
            "Judge relevance only, not factual accuracy."
        ),
        rules=_bullets(
            "Ignore whether the answer is factually correct.",
            "Score only how well the answer addresses what was asked.",
            "Keep reasoning short.",
        ),
        scale=_bullets(
            "5: fully addresses what was asked",
            "4: addresses it, with minor digressions or minor parts missing",
            "3: partial or generic answer",
            "2: tangential, mostly about something else",
            "1: does not answer the question, or is off-topic",
        ),
        example_reasoning="Fully addresses the question with the key detail.",
        example_level=5,
    ),
    "groundedness": _rubric(
        step="rubric_groundedness",
        role="You are an evaluation judge for groundedness.",
        task="Rate how well the ANSWER is supported by the DOCUMENTS.",
        rules=_bullets(
            "Use only the documents; never outside knowledge.",
            "Keep reasoning short.",
        ),
        scale=_bullets(
            "5: every factual statement is supported by the documents",
            "4: all key statements are supported; a minor detail is not",
            "3: a mix of supported and unsupported statements",
            "2: most statements are unsupported",
            "1: unsupported, or contradicts the documents",
        ),
        example_reasoning="All key facts appear in the retrieved documents.",
        example_level=5,
    ),
    "correctness": _rubric(
        step="rubric_correctness",
        role="You are an evaluation judge for correctness against a reference.",
        task="Rate how well the ANSWER matches the REFERENCE ANSWER.",
        rules=_bullets(
            "Extra correct details in the answer are fine; contradictions are not.",
            "Keep reasoning short.",
        ),
        scale=_bullets(
            "5: conveys every fact of the reference, no contradictions",
            "4: conveys the key facts, minor ones missing, no contradictions",
            "3: conveys about half of the facts, no contradictions",
            "2: conveys few of the facts",
            "1: conveys none of the facts, or contradicts the reference",
        ),
        example_reasoning="Conveys every reference fact with no contradictions.",
        example_level=5,
    ),
    "context_precision": _rubric(
        step="rubric_context_precision",
        role="You are an evaluation judge for context precision.",
        task=(
            "Rate how precisely the DOCUMENTS support producing the REFERENCE ANSWER "
            "to the QUESTION."
        ),
        rules=_bullets(
            "Prefer early relevant documents; penalize noise.",
            "Keep reasoning short.",
        ),
        scale=_bullets(
            "5: every document is useful; ranking puts useful ones first",
            "4: almost all documents are useful; little noise",
            "3: a mix of useful and irrelevant documents",
            "2: most documents are irrelevant",
            "1: documents are irrelevant or actively misleading for the reference answer",
        ),
        example_reasoning="Useful documents ranked first with little noise.",
        example_level=5,
    ),
    "context_recall": _rubric(
        step="rubric_context_recall",
        role="You are an evaluation judge for context recall.",
        task=(
            "Rate how completely the DOCUMENTS cover the facts in the REFERENCE ANSWER "
            "to the QUESTION."
        ),
        rules=_bullets(
            "Use only the documents; never outside knowledge.",
            "Keep reasoning short.",
        ),
        scale=_bullets(
            "5: every fact of the reference is present in the documents",
            "4: all key facts are present; a minor detail is missing",
            "3: about half of the reference facts are present",
            "2: few reference facts are present",
            "1: documents omit the reference facts, or contradict them",
        ),
        example_reasoning="Every reference fact is present in the documents.",
        example_level=5,
    ),
}

# System templates used per (kind, method). Keys are stable snapshot names.
_CLAIMS_BUNDLES: dict[str, dict[str, str]] = {
    "groundedness": {
        "extract_answer_claims": EXTRACT_ANSWER_CLAIMS,
        "verify_against_documents": VERIFY_AGAINST_DOCUMENTS,
    },
    "correctness": {
        "extract_answer_claims": EXTRACT_ANSWER_CLAIMS,
        "extract_reference_claims": EXTRACT_REFERENCE_CLAIMS,
        "verify_against_reference": VERIFY_AGAINST_REFERENCE,
        "verify_reference_coverage": VERIFY_REFERENCE_COVERAGE,
    },
    "context_precision": {
        "verify_context_relevance": VERIFY_CONTEXT_RELEVANCE,
    },
    "context_recall": {
        "extract_reference_claims": EXTRACT_REFERENCE_CLAIMS,
        "verify_context_coverage": VERIFY_CONTEXT_COVERAGE,
    },
}


def bundle_for(kind: str, method: str) -> dict[str, str]:
    """Return the system prompt texts that (kind, method) uses."""
    method = method.strip().lower()
    kind = kind.strip().lower()
    if method == "rubric":
        if kind not in RUBRICS:
            raise ValueError(f"unknown rubric kind: {kind!r}")
        return {f"rubric_{kind}": RUBRICS[kind]}
    if method == "claims":
        bundle = _CLAIMS_BUNDLES.get(kind)
        if bundle is None:
            raise ValueError(f"unknown claims kind: {kind!r}")
        return dict(bundle)
    raise ValueError(f"unknown judge method: {method!r}")


def content_hash(bundle: dict[str, str]) -> str:
    """Full SHA-256 of a canonical JSON encoding of the prompt bundle."""
    canonical = json.dumps(bundle, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def prompt_version(kind: str, method: str) -> str:
    digest = content_hash(bundle_for(kind, method))
    return f"{kind}.{method}.{digest[:_SHORT_HASH_LEN]}"


def as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def render_claims(claims: list[str]) -> str:
    n = len(claims)
    header = (
        f'Claim count: {n}. Emit exactly {n} objects in "verdicts", '
        f"one each for [C1]..[C{n}] in order."
    )
    body = "\n".join(f"[C{i}] {' '.join(claim.split())}" for i, claim in enumerate(claims, 1))
    return f"{header}\n{body}" if body else header


def render_documents(documents: list[Any]) -> str:
    blocks: list[str] = []
    for doc in documents:
        if not isinstance(doc, dict):
            continue
        header = f"[doc:{doc.get('id', '?')}]"
        if doc.get("title"):
            header += " " + " ".join(str(doc["title"]).split())
        blocks.append(f"{header}\n{as_text(doc.get('text'))}")
    return "\n\n".join(blocks)


def render_numbered_documents(documents: list[Any]) -> str:
    blocks: list[str] = []
    for i, doc in enumerate(documents, start=1):
        if not isinstance(doc, dict):
            continue
        header = f"[D{i}] id={doc.get('id', '?')}"
        if doc.get("title"):
            header += " " + " ".join(str(doc["title"]).split())
        blocks.append(f"{header}\n{as_text(doc.get('text'))}")
    n = len(blocks)
    count_line = (
        f'Document count: {n}. Emit exactly {n} objects in "verdicts", '
        f"one each for [D1]..[D{n}] in order."
    )
    body = "\n\n".join(blocks)
    return f"{count_line}\n\n{body}" if body else count_line


def sections(**parts: str) -> str:
    return "\n\n".join(f"{name.upper().replace('_', ' ')}:\n{text}" for name, text in parts.items())
