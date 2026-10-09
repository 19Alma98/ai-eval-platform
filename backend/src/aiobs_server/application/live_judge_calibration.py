from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from aiobs_server.application.projects import ProjectNotFoundError
from aiobs_server.domain.live_interaction import LiveInteractionScore, LiveScoreReview
from aiobs_server.domain.repositories import LiveInteractionRepository, ProjectRepository

_EXCLUDED_LABELS = frozenset({"ERROR", "SKIPPED"})
_DEFAULT_LOOKBACK = timedelta(days=90)


@dataclass(frozen=True, slots=True)
class JudgeCalibrationBucket:
    kind: str
    model: str | None
    method: str | None
    prompt_version: str | None
    n_reviewed: int
    n_agree: int
    n_disagree: int
    agreement_rate: float
    n_explanation_edits: int
    explanation_edit_rate: float


def _meta_str(metadata: dict[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _group_key(score: LiveInteractionScore) -> tuple[str, str | None, str | None, str | None]:
    return (
        score.kind,
        _meta_str(score.metadata, "model"),
        _meta_str(score.metadata, "method"),
        _meta_str(score.metadata, "prompt_version"),
    )


def aggregate_calibration(
    rows: list[tuple[LiveInteractionScore, LiveScoreReview]],
) -> list[JudgeCalibrationBucket]:
    """Group reviewed scores by kind × judge model (and method / prompt_version)."""
    counts: dict[tuple[str, str | None, str | None, str | None], list[int]] = defaultdict(
        lambda: [0, 0, 0, 0]
    )
    # [n_reviewed, n_agree, n_disagree, n_explanation_edits]
    for score, review in rows:
        label = (score.label or "").strip().upper()
        if label in _EXCLUDED_LABELS:
            continue
        key = _group_key(score)
        bucket = counts[key]
        bucket[0] += 1
        if review.verdict == "agree":
            bucket[1] += 1
        elif review.verdict == "disagree":
            bucket[2] += 1
        if review.corrected_explanation is not None:
            bucket[3] += 1

    out: list[JudgeCalibrationBucket] = []
    for (kind, model, method, prompt_version), (
        n_reviewed,
        n_agree,
        n_disagree,
        n_edits,
    ) in sorted(counts.items(), key=lambda item: (item[0][0], item[0][1] or "")):
        if n_reviewed == 0:
            continue
        out.append(
            JudgeCalibrationBucket(
                kind=kind,
                model=model,
                method=method,
                prompt_version=prompt_version,
                n_reviewed=n_reviewed,
                n_agree=n_agree,
                n_disagree=n_disagree,
                agreement_rate=n_agree / n_reviewed,
                n_explanation_edits=n_edits,
                explanation_edit_rate=n_edits / n_reviewed,
            )
        )
    return out


class SummarizeLiveJudgeCalibration:
    def __init__(
        self,
        projects: ProjectRepository,
        live: LiveInteractionRepository,
    ) -> None:
        self._projects = projects
        self._live = live

    async def execute(
        self,
        project_id: uuid.UUID,
        *,
        since: datetime | None = None,
    ) -> list[JudgeCalibrationBucket]:
        project = await self._projects.get_by_id(project_id)
        if project is None:
            raise ProjectNotFoundError(project_id)

        if since is None:
            since = datetime.now(UTC) - _DEFAULT_LOOKBACK
        elif since.tzinfo is None:
            since = since.replace(tzinfo=UTC)

        rows = await self._live.list_calibration_rows(project_id, since=since)
        return aggregate_calibration(rows)
