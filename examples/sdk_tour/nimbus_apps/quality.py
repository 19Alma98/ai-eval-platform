"""Custom quality metrics for the Nimbus assistant, written as plain Python.

A metric is a function decorated with ``@opengrade.metric`` that receives an
``opengrade.Sample`` (input, output, expected, documents, metadata, ...) and returns a
score: ``opengrade.Score``, a float in [0, 1], a bool or ``None`` (= skipped).

The same functions are used in two places, so tests and production measure the same thing:

- in experiments, ``og.evaluate(..., metrics=[cites_retrieved_source])``
  (scripts 02 and 03): ``Sample.expected`` and ``Sample.metadata`` come from the dataset;
- in production, ``@og.trace(metrics=[cites_retrieved_source])`` (script 04):
  there is no expected answer, so metrics that ``requires=("expected",)`` are skipped.

Scores are stored on the platform, shown per item in the UI, compared with the baseline
and can be gated / alerted on, exactly like the built-in metrics.
"""

from __future__ import annotations

import re

import opengrade

from nimbus_apps.llm import REFUSAL

_CITATION = re.compile(r"\[([\w-]+)\]")


def is_refusal(answer: str) -> bool:
    return answer.strip().lower().startswith(("i don't know", "i do not know"))


@opengrade.metric(threshold=1.0, version=1, requires=("output", "documents"))
def cites_retrieved_source(s: opengrade.Sample) -> opengrade.Score:
    """Every [source-id] cited in the answer must be one of the retrieved documents.

    Catches invented citations. A refusal needs no citation (skipped).
    """
    answer = str(s.output)
    if is_refusal(answer):
        return opengrade.Score(label="SKIPPED", explanation="refusal: nothing to cite")
    cited = set(_CITATION.findall(answer))
    retrieved = {str(d.get("id")) for d in s.documents}
    if not cited:
        return opengrade.Score(0.0, explanation="no citation in the answer")
    invented = sorted(cited - retrieved)
    if invented:
        return opengrade.Score(0.0, explanation=f"cites documents not retrieved: {invented}")
    return opengrade.Score(1.0, explanation=f"cites {sorted(cited)}")


@opengrade.metric(threshold=1.0, version=1, requires=("output",))
def refusal_is_correct(s: opengrade.Sample) -> opengrade.Score:
    """Refuse exactly when the question cannot be answered from the documentation.

    Uses the dataset field ``metadata.answerable`` (only available in experiments).
    """
    if "answerable" not in s.metadata:
        return opengrade.Score(label="SKIPPED", explanation="metadata.answerable missing")
    refused = is_refusal(str(s.output))
    answerable = bool(s.metadata["answerable"])
    outcome = {
        (True, False): "correct_answer",
        (False, True): "correct_refusal",
        (True, True): "over_refusal",  # refused a question the docs do answer
        (False, False): "missed_refusal",  # answered something the docs do not cover
    }[(answerable, refused)]
    ok = outcome.startswith("correct")
    return opengrade.Score(1.0 if ok else 0.0, explanation=outcome, metadata={"outcome": outcome})


@opengrade.metric(threshold=1.0, version=1, requires=("output",))
def answer_is_concise(s: opengrade.Sample) -> opengrade.Score:
    """Support answers must fit in a chat bubble: at most 60 words."""
    words = len(str(s.output).split())
    return opengrade.Score(float(words <= 60), explanation=f"{words} words")


__all__ = [
    "REFUSAL",
    "answer_is_concise",
    "cites_retrieved_source",
    "is_refusal",
    "refusal_is_correct",
]
