from __future__ import annotations

import pytest

from aiobs_server.evaluation.judges import prompts
from aiobs_server.evaluation.judges.claims import (
    coverage_claim_records,
    extract_claims,
    f1,
    limit_claims,
    score_coverage,
    score_support,
    support_claim_records,
    verify_coverage,
    verify_support,
)
from aiobs_server.evaluation.judges.parsing import CallOptions
from aiobs_server.evaluation.judges.schemas import CoverageVerdict, SupportVerdict
from support.fake_llm import ScriptedJudgeLlm

_OPTS = CallOptions(model=None, temperature=None)


def _sv(verdict: str) -> SupportVerdict:
    return SupportVerdict(verdict=verdict, reasoning="r")


def _cv(verdict: str) -> CoverageVerdict:
    return CoverageVerdict(verdict=verdict, reasoning="r")


def test_score_support() -> None:
    s = score_support(
        [_sv("supported"), _sv("supported"), _sv("not_supported"), _sv("contradicted")]
    )
    assert s.score == 0.5
    assert (s.n_claims, s.n_supported, s.n_contradicted, s.n_not_supported) == (4, 2, 1, 1)


def test_score_coverage_recall_and_contradiction_zeroes() -> None:
    ok = score_coverage([_cv("covered"), _cv("covered"), _cv("missing"), _cv("covered")])
    assert ok.recall == 0.75
    assert ok.score == 0.75
    bad = score_coverage([_cv("covered"), _cv("contradicted")])
    assert bad.recall == 0.5
    assert bad.score == 0.0
    assert bad.n_contradicted == 1


def test_f1() -> None:
    assert f1(1.0, 0.5) == pytest.approx(2 / 3)
    assert f1(0.0, 0.0) == 0.0


def test_limit_claims() -> None:
    assert limit_claims(["a", "b", "c"], 2) == (["a", "b"], True)
    assert limit_claims(["a"], 2) == (["a"], False)


def test_claim_records() -> None:
    verdict = SupportVerdict(verdict="supported", reasoning="r", doc_ids=["kb-1"], quote="q")
    assert support_claim_records(["c"], [verdict]) == [
        {"text": "c", "verdict": "supported", "doc_ids": ["kb-1"], "quote": "q", "reasoning": "r"}
    ]
    assert coverage_claim_records(["g"], [_cv("missing")]) == [
        {"text": "g", "verdict": "missing", "reasoning": "r"}
    ]


@pytest.mark.asyncio
async def test_extract_claims_returns_all_claims() -> None:
    llm = ScriptedJudgeLlm({"extract_answer_claims": {"claims": ["a", " ", "b"]}})
    out = await extract_claims(llm, system=prompts.EXTRACT_ANSWER_CLAIMS, user="u", options=_OPTS)
    assert out.claims == ["a", "b"]
    assert out.calls == 1
    assert out.cache_hit is False


@pytest.mark.asyncio
async def test_verify_support_repairs_wrong_verdict_count() -> None:
    llm = ScriptedJudgeLlm(
        {
            "verify_against_documents": [
                {"verdicts": [{"verdict": "supported"}]},
                {"verdicts": [{"verdict": "supported"}, {"verdict": "contradicted"}]},
            ]
        }
    )
    verdicts, calls = await verify_support(
        llm, system=prompts.VERIFY_AGAINST_DOCUMENTS, user="u", n=2, options=_OPTS
    )
    assert [v.verdict for v in verdicts] == ["supported", "contradicted"]
    assert calls == 2
    assert "expected 2 verdicts" in llm.calls[1]["history"][1]["content"]


@pytest.mark.asyncio
async def test_verify_coverage_default_reply_counts_claims() -> None:
    llm = ScriptedJudgeLlm()
    user = prompts.sections(reference_claims=prompts.render_claims(["a", "b", "c"]))
    verdicts, calls = await verify_coverage(
        llm, system=prompts.VERIFY_REFERENCE_COVERAGE, user=user, n=3, options=_OPTS
    )
    assert [v.verdict for v in verdicts] == ["covered"] * 3
    assert calls == 1
