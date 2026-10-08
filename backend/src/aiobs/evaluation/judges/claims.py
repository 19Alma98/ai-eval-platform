from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from aiobs.evaluation.judges.parsing import CallOptions, call_structured
from aiobs.evaluation.judges.schemas import (
    CoverageVerdict,
    CoverageVerifyOut,
    ExtractOut,
    SupportVerdict,
    SupportVerifyOut,
)
from aiobs.evaluation.protocol import LlmClient


@dataclass(frozen=True, slots=True)
class ExtractedClaims:
    claims: list[str]
    calls: int
    cache_hit: bool = False


@dataclass(frozen=True, slots=True)
class SupportScore:
    score: float
    n_claims: int
    n_supported: int
    n_contradicted: int
    n_not_supported: int


@dataclass(frozen=True, slots=True)
class CoverageScore:
    score: float
    recall: float
    n_gold: int
    n_covered: int
    n_contradicted: int
    n_missing: int


def _expect_verdicts(n: int) -> Callable[[Any], None]:
    def check(out: Any) -> None:
        if len(out.verdicts) != n:
            raise ValueError(
                f"expected {n} verdicts (one per claim, same order), got {len(out.verdicts)}"
            )

    return check


async def extract_claims(
    llm: LlmClient, *, system: str, user: str, options: CallOptions
) -> ExtractedClaims:
    out = await call_structured(llm, system=system, user=user, schema=ExtractOut, options=options)
    return ExtractedClaims(claims=out.value.claims, calls=out.calls)


async def verify_support(
    llm: LlmClient, *, system: str, user: str, n: int, options: CallOptions
) -> tuple[list[SupportVerdict], int]:
    out = await call_structured(
        llm,
        system=system,
        user=user,
        schema=SupportVerifyOut,
        options=options,
        check=_expect_verdicts(n),
    )
    return out.value.verdicts, out.calls


async def verify_coverage(
    llm: LlmClient, *, system: str, user: str, n: int, options: CallOptions
) -> tuple[list[CoverageVerdict], int]:
    out = await call_structured(
        llm,
        system=system,
        user=user,
        schema=CoverageVerifyOut,
        options=options,
        check=_expect_verdicts(n),
    )
    return out.value.verdicts, out.calls


def limit_claims(claims: list[str], max_claims: int) -> tuple[list[str], bool]:
    return claims[:max_claims], len(claims) > max_claims


def score_support(verdicts: list[SupportVerdict]) -> SupportScore:
    n = len(verdicts)
    supported = sum(1 for v in verdicts if v.verdict == "supported")
    contradicted = sum(1 for v in verdicts if v.verdict == "contradicted")
    return SupportScore(
        score=supported / n if n else 0.0,
        n_claims=n,
        n_supported=supported,
        n_contradicted=contradicted,
        n_not_supported=n - supported - contradicted,
    )


def score_coverage(verdicts: list[CoverageVerdict]) -> CoverageScore:
    n = len(verdicts)
    covered = sum(1 for v in verdicts if v.verdict == "covered")
    contradicted = sum(1 for v in verdicts if v.verdict == "contradicted")
    recall = covered / n if n else 0.0
    return CoverageScore(
        # An answer that contradicts the reference is wrong, whatever else it covers.
        score=0.0 if contradicted else recall,
        recall=recall,
        n_gold=n,
        n_covered=covered,
        n_contradicted=contradicted,
        n_missing=n - covered - contradicted,
    )


def f1(precision: float, recall: float) -> float:
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def support_claim_records(
    claims: list[str], verdicts: list[SupportVerdict]
) -> list[dict[str, Any]]:
    return [
        {
            "text": claim,
            "verdict": v.verdict,
            "doc_ids": list(v.doc_ids),
            "quote": v.quote,
            "reasoning": v.reasoning,
        }
        for claim, v in zip(claims, verdicts, strict=True)
    ]


def coverage_claim_records(
    claims: list[str], verdicts: list[CoverageVerdict]
) -> list[dict[str, Any]]:
    return [
        {"text": claim, "verdict": v.verdict, "reasoning": v.reasoning}
        for claim, v in zip(claims, verdicts, strict=True)
    ]
