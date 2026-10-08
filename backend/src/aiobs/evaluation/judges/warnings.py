from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Protocol

from aiobs.evaluation.judges.errors import JUDGE_OUTPUT_INVALID

JUDGE_MODEL_UNSUITABLE = "judge_model_unsuitable"
UNSUITABLE_RATE = 0.20


class _ScoredRow(Protocol):
    @property
    def label(self) -> str | None: ...

    @property
    def metadata(self) -> Mapping[str, Any]: ...


def unsuitable_model_warning(
    results: Iterable[_ScoredRow],
) -> dict[str, Any] | None:
    """Flag a run whose judge model fails the output format on more than 20% of items.

    SKIPPED and missing-output items were never judged, so they are excluded.
    Provider errors count as evaluated but not as format failures.
    Accepts offline EvaluationResultRecord or live LiveInteractionScore rows.
    """
    evaluated = [
        r
        for r in results
        if (r.label or "").strip().upper() != "SKIPPED" and not r.metadata.get("missing_output")
    ]
    invalid = [r for r in evaluated if r.metadata.get("error_type") == JUDGE_OUTPUT_INVALID]
    if not evaluated or len(invalid) / len(evaluated) <= UNSUITABLE_RATE:
        return None
    rate = len(invalid) / len(evaluated)
    model = invalid[0].metadata.get("model")
    method = invalid[0].metadata.get("method")
    return {
        "model": model,
        "method": method,
        "failure_rate": rate,
        "message": (
            f"Judge model {model} returned unusable output on {rate:.0%} of items with "
            f"method '{method}'. Use method: rubric or a stronger judge model."
        ),
    }
