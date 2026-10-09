from __future__ import annotations

from aiobs_server.evaluation.judges.parsing import CallOptions, call_structured
from aiobs_server.evaluation.judges.schemas import RubricOut
from aiobs_server.evaluation.protocol import LlmClient


def level_to_score(level: int) -> float:
    """Map rubric level 1..5 onto 0..1 (1 → 0.0, 3 → 0.5, 5 → 1.0)."""
    return (level - 1) / 4


async def rubric_judge(
    llm: LlmClient, *, system: str, user: str, options: CallOptions
) -> tuple[RubricOut, int]:
    out = await call_structured(llm, system=system, user=user, schema=RubricOut, options=options)
    return out.value, out.calls
