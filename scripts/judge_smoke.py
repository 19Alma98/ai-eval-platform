"""Manual smoke test of the v3 LLM judges against a real model (not run in CI).

Usage (from backend/):
    LLM_MODEL=ollama/gemma4:e2b LLM_API_BASE=http://localhost:11434 \
        uv run python ../scripts/judge_smoke.py [--method rubric]

With a capable model, expect roughly: groundedness 0.5 (the carry-over claim contradicts
"up to 5 days"), correctness 0.5 (the HR portal is missing), answer_relevance 1.0.
"""

from __future__ import annotations

import argparse
import asyncio
import json

from aiobs.config import get_settings
from aiobs.evaluation.judges.evaluators import JUDGE_KINDS, JudgeDefaults, create_llm_judge
from aiobs.evaluation.protocol import EvaluationSample
from aiobs.infrastructure.llm import LiteLlmClient

SAMPLE = EvaluationSample(
    input="How many days of paid time off do full-time employees get?",
    expected_output="Full-time employees get 26 days of PTO per year, requested via the HR portal.",
    actual_output=(
        "Full-time employees receive 26 days of PTO per year. "
        "Unused days can be carried over indefinitely."
    ),
    context={
        "documents": [
            {
                "id": "kb-pto",
                "title": "PTO policy",
                "text": "Full-time employees accrue 26 days of paid time off per year. "
                "Requests go through the HR portal. Up to 5 unused days carry over.",
            }
        ]
    },
    metadata={},
)


async def main(method: str | None) -> None:
    settings = get_settings()
    llm = LiteLlmClient(settings)
    defaults = JudgeDefaults(model=settings.llm_model)
    for kind in JUDGE_KINDS:
        config = {"method": method} if method and kind != "answer_relevance" else {}
        judge = create_llm_judge(kind, config, llm, defaults=defaults)
        result = await judge.evaluate(SAMPLE)
        print(f"\n== {kind} ({judge.prompt_version}) score={result.score} label={result.label}")
        print(result.explanation)
        print(json.dumps(result.metadata, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--method", choices=["claims", "rubric"], default=None)
    asyncio.run(main(parser.parse_args().method))
