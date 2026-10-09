from __future__ import annotations

from datetime import datetime, timedelta

from aiobs.domain.live_overview import (
    LiveAttentionItem,
    LiveInteractionInRange,
    LiveOverviewStats,
    LiveSeriesBucket,
)

__all__ = [
    "LiveAttentionItem",
    "LiveInteractionInRange",
    "LiveOverviewStats",
    "LiveSeriesBucket",
    "bucket_size_for_range",
]


def bucket_size_for_range(since: datetime, until: datetime) -> timedelta:
    span = until - since
    if span <= timedelta(hours=1):
        return timedelta(minutes=5)
    if span <= timedelta(hours=6):
        return timedelta(minutes=15)
    if span <= timedelta(days=1):
        return timedelta(hours=1)
    return timedelta(hours=6)
