"""Scores per OTel trace: SDK metrics, end-user feedback, external judges."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from aiobs_server.application.projects import ProjectNotFoundError
from aiobs_server.domain.repositories import ProjectRepository, TraceScoreRepository
from aiobs_server.domain.trace_score import (
    MAX_TRACE_SCORE_BATCH,
    TraceScore,
    TraceScoreSummaryRow,
    normalize_trace_id,
)
from aiobs_server.evaluation.outcomes import item_verdict


@dataclass(frozen=True, slots=True)
class TraceScoreInput:
    trace_id: str
    name: str
    value: float | int | None = None
    label: str | None = None
    explanation: str | None = None
    threshold: float | int | None = None
    source: str = "sdk"
    author: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class LogTraceScores:
    def __init__(self, projects: ProjectRepository, scores: TraceScoreRepository) -> None:
        self._projects = projects
        self._scores = scores

    async def execute(self, project_id: uuid.UUID, items: Sequence[TraceScoreInput]) -> int:
        if await self._projects.get_by_id(project_id) is None:
            raise ProjectNotFoundError(project_id)
        if not items:
            raise ValueError("scores must not be empty")
        if len(items) > MAX_TRACE_SCORE_BATCH:
            raise ValueError(f"at most {MAX_TRACE_SCORE_BATCH} scores per request")
        # Build (and validate) everything before writing: the batch is all-or-nothing.
        built: dict[tuple[uuid.UUID, str, str, str, str], TraceScore] = {}
        for item in items:
            score = TraceScore.create(
                project_id,
                item.trace_id,
                item.name,
                value=item.value,
                label=item.label,
                explanation=item.explanation,
                threshold=item.threshold,
                source=item.source,
                author=item.author,
                metadata=item.metadata,
            )
            # Same PASS/FAIL rule as client results and live judge scores.
            score = score.with_label(item_verdict(score.value, score.label, score.threshold))
            built[score.key] = score  # duplicate keys in one batch: the last one wins
        return await self._scores.upsert_many(list(built.values()))


class ListTraceScores:
    def __init__(self, scores: TraceScoreRepository) -> None:
        self._scores = scores

    async def execute(self, project_id: uuid.UUID, trace_id: str) -> list[TraceScore]:
        try:
            normalized = normalize_trace_id(trace_id)
        except ValueError:
            return []
        found = await self._scores.list_by_trace_ids(project_id, [normalized])
        return found.get(normalized, [])


class SummarizeTraceScores:
    def __init__(self, projects: ProjectRepository, scores: TraceScoreRepository) -> None:
        self._projects = projects
        self._scores = scores

    async def execute(
        self, project_id: uuid.UUID, *, since: datetime, until: datetime
    ) -> list[TraceScoreSummaryRow]:
        if await self._projects.get_by_id(project_id) is None:
            raise ProjectNotFoundError(project_id)
        if since >= until:
            raise ValueError("since must be before until")
        return await self._scores.summarize(project_id, since=since, until=until)
