"""All LLM judge prompt text.

Changing any template changes judge behaviour: bump PROMPT_REVISION so runs scored
with different prompts are flagged as not comparable.
"""

from __future__ import annotations

import json
from typing import Any

PROMPT_REVISION = "v3"
STEP_PREFIX = "STEP: "


def prompt_version(kind: str, method: str) -> str:
    return f"{kind}.{method}.{PROMPT_REVISION}"


def _system(step: str, body: str) -> str:
    return f"{STEP_PREFIX}{step}\n{body.strip()}"


_EXTRACT_RULES = """
Rules:
- One fact per claim. Split compound sentences into separate claims.
- Each claim must be understandable on its own: replace pronouns and references with
  what they refer to, using the QUESTION for context.
- Keep the original wording, numbers, dates and names. Do not add, infer or correct facts.
- Skip text with no factual content (greetings, apologies, offers of further help,
  restating the question).
- If there are no factual claims (for example a refusal or "I don't know"), return an
  empty list.
"""

EXTRACT_ANSWER_CLAIMS = _system(
    "extract_answer_claims",
    f"""
You are an evaluation assistant. Break the ANSWER into atomic factual claims.
{_EXTRACT_RULES}
Respond with JSON only: {{"claims": ["<claim>", ...]}}
""",
)

EXTRACT_REFERENCE_CLAIMS = _system(
    "extract_reference_claims",
    f"""
You are an evaluation assistant. Break the REFERENCE ANSWER into atomic factual claims.
{_EXTRACT_RULES}
Respond with JSON only: {{"claims": ["<claim>", ...]}}
""",
)

VERIFY_AGAINST_DOCUMENTS = _system(
    "verify_against_documents",
    """
You are an evaluation judge. For each CLAIM ([C1], [C2], ...) decide whether the
DOCUMENTS support it.
Verdicts:
- "supported": the documents state it, or it follows directly from them.
- "contradicted": the documents state something incompatible with it.
- "not_supported": the documents do not mention it, or support it only partially.
Use only the documents, never outside knowledge. Judge each claim independently.
Return exactly one verdict per claim, in the same order. Write your reasoning before
choosing the verdict. List the ids of the documents you relied on in "doc_ids" and copy
the shortest supporting or contradicting passage into "quote" (null if none).
Respond with JSON only: {"verdicts": [{"reasoning": "<why>", "verdict": "supported" |
"contradicted" | "not_supported", "doc_ids": ["<id>"], "quote": "<passage>" | null}, ...]}
""",
)

VERIFY_AGAINST_REFERENCE = _system(
    "verify_against_reference",
    """
You are an evaluation judge. For each CLAIM ([C1], [C2], ...) taken from an answer,
decide whether the REFERENCE ANSWER supports it.
Verdicts:
- "supported": the reference states it, or it follows directly from it.
- "contradicted": the reference states something incompatible with it.
- "not_supported": the reference does not mention it.
Use only the reference answer, never outside knowledge. Return exactly one verdict per
claim, in the same order. Write your reasoning before choosing the verdict.
Respond with JSON only: {"verdicts": [{"reasoning": "<why>", "verdict": "supported" |
"contradicted" | "not_supported"}, ...]}
""",
)

VERIFY_REFERENCE_COVERAGE = _system(
    "verify_reference_coverage",
    """
You are an evaluation judge. For each REFERENCE CLAIM ([C1], [C2], ...) decide whether
the ANSWER conveys it.
Verdicts:
- "covered": the answer states the same fact. Wording may differ; numbers, dates, names
  and conditions must match.
- "contradicted": the answer states something incompatible with it.
- "missing": the answer does not state it.
Extra information in the answer is not your concern. Return exactly one verdict per
reference claim, in the same order. Write your reasoning before choosing the verdict.
Respond with JSON only: {"verdicts": [{"reasoning": "<why>", "verdict": "covered" |
"contradicted" | "missing"}, ...]}
""",
)

_RUBRIC_FORMAT = 'Respond with JSON only: {"reasoning": "<why>", "level": <1-5>}'

RUBRICS: dict[str, str] = {
    "answer_relevance": _system(
        "rubric_answer_relevance",
        f"""
You are an evaluation judge. Rate how relevant the ANSWER is to the QUESTION. Judge
relevance only, not factual accuracy.
5: fully addresses what was asked
4: addresses it, with minor digressions or minor parts missing
3: partial or generic answer
2: tangential, mostly about something else
1: does not answer the question, or is off-topic
Write your reasoning before choosing the level.
{_RUBRIC_FORMAT}
""",
    ),
    "groundedness": _system(
        "rubric_groundedness",
        f"""
You are an evaluation judge. Rate how well the ANSWER is supported by the DOCUMENTS.
Use only the documents, never outside knowledge.
5: every factual statement is supported by the documents
4: all key statements are supported; a minor detail is not
3: a mix of supported and unsupported statements
2: most statements are unsupported
1: unsupported, or contradicts the documents
Write your reasoning before choosing the level.
{_RUBRIC_FORMAT}
""",
    ),
    "correctness": _system(
        "rubric_correctness",
        f"""
You are an evaluation judge. Rate how well the ANSWER matches the REFERENCE ANSWER.
Extra correct details in the answer are fine; contradictions are not.
5: conveys every fact of the reference, no contradictions
4: conveys the key facts, minor ones missing, no contradictions
3: conveys about half of the facts, no contradictions
2: conveys few of the facts
1: conveys none of the facts, or contradicts the reference
Write your reasoning before choosing the level.
{_RUBRIC_FORMAT}
""",
    ),
}


def as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def render_claims(claims: list[str]) -> str:
    return "\n".join(f"[C{i}] {claim}" for i, claim in enumerate(claims, 1))


def render_documents(documents: list[Any]) -> str:
    blocks: list[str] = []
    for doc in documents:
        if not isinstance(doc, dict):
            continue
        header = f"[doc:{doc.get('id', '?')}]"
        if doc.get("title"):
            header += f" {doc['title']}"
        blocks.append(f"{header}\n{as_text(doc.get('text'))}")
    return "\n\n".join(blocks)


def sections(**parts: str) -> str:
    return "\n\n".join(f"{name.upper().replace('_', ' ')}:\n{text}" for name, text in parts.items())
