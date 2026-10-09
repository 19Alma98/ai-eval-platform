from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from aiobs.domain.live_interaction import LiveInteraction, LiveInteractionScore


@dataclass(frozen=True, slots=True)
class LiveSeriesBucket:
    bucket_start: datetime
    n: int
    mean_score: float | None
    fail_rate: float | None


@dataclass(frozen=True, slots=True)
class LiveAttentionItem:
    interaction_id: uuid.UUID
    question: str
    created_at: datetime
    reason: str  # "fail"


@dataclass(frozen=True, slots=True)
class LiveOverviewStats:
    n_interactions: int
    n_failed: int
    n_pending: int
    mean_score: float | None
    fail_rate: float | None
    series: list[LiveSeriesBucket]
    attention: list[LiveAttentionItem]


@dataclass(frozen=True, slots=True)
class LiveInteractionInRange:
    """Live interaction within a time window, with scores loaded for aggregation."""

    interaction: LiveInteraction
    scores: list[LiveInteractionScore]


@dataclass(frozen=True, slots=True)
class LiveInRangeResult:
    items: list[LiveInteractionInRange]
    truncated: bool
