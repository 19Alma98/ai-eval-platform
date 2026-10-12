from __future__ import annotations

import hashlib
import random
import uuid
from collections.abc import Sequence

from aiobs_server.regression.policy import percentile_nearest_rank

DEFAULT_N_BOOT = 2000
DEFAULT_ALPHA = 0.05


def comparison_seed(
    evaluator_id: uuid.UUID,
    candidate_run_id: uuid.UUID,
    baseline_run_id: uuid.UUID,
    metric: str,
) -> int:
    raw = f"{evaluator_id}:{candidate_run_id}:{baseline_run_id}:{metric}".encode()
    return int.from_bytes(hashlib.blake2b(raw, digest_size=8).digest(), "big")


def paired_mean_ci(
    diffs: Sequence[float],
    *,
    n_boot: int = DEFAULT_N_BOOT,
    seed: int,
    alpha: float = DEFAULT_ALPHA,
) -> tuple[float, float]:
    """Percentile bootstrap CI for the mean of paired differences."""
    if not diffs:
        raise ValueError("diffs must be non-empty")
    if n_boot < 1:
        raise ValueError("n_boot must be >= 1")
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must be in (0, 1)")

    rng = random.Random(seed)
    n = len(diffs)
    means: list[float] = []
    for _ in range(n_boot):
        total = 0.0
        for _ in range(n):
            total += diffs[rng.randrange(n)]
        means.append(total / n)

    low_pct = (alpha / 2.0) * 100.0
    high_pct = (1.0 - alpha / 2.0) * 100.0
    return percentile_nearest_rank(means, low_pct), percentile_nearest_rank(means, high_pct)
