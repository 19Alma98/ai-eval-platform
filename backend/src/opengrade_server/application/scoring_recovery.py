from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime

from opengrade_server.application.background_tasks import spawn
from opengrade_server.application.live_interactions import schedule_live_score
from opengrade_server.domain.repositories import (
    EvaluationRunRepository,
    ExperimentRepository,
    LiveInteractionRepository,
)

logger = logging.getLogger(__name__)

_LIVE_REQUEUE_CONCURRENCY = 4


async def fail_stuck_experiments(
    experiments: ExperimentRepository,
    runs: EvaluationRunRepository,
) -> int:
    """Mark experiments left in ``running`` as ``failed``; orphan runs → ERROR.

    Does not re-score: evaluation runs are append-only.
    """
    stuck = await experiments.list_by_status("running")
    if not stuck:
        return 0
    now = datetime.now(UTC)
    for experiment in stuck:
        experiment_runs = await runs.list_runs_by_experiment(experiment.id)
        for run in experiment_runs:
            if run.status not in {"PENDING", "RUNNING"}:
                continue
            metadata = dict(run.metadata)
            metadata["error"] = "Interrupted by API restart"
            await runs.update_run(run.with_status("ERROR", finished_at=now, metadata=metadata))
        await experiments.update(experiment.with_status("failed"))
        logger.warning("Marked stuck experiment as failed after restart: %s", experiment.id)
    return len(stuck)


async def requeue_unfinished_live_scores(
    live: LiveInteractionRepository,
    *,
    concurrency: int = _LIVE_REQUEUE_CONCURRENCY,
) -> int:
    """Reset ``running`` → ``pending`` and re-schedule background scoring."""
    unfinished = await live.list_by_judge_statuses(frozenset({"pending", "running"}))
    if not unfinished:
        return 0

    ids: list[uuid.UUID] = []
    for interaction in unfinished:
        if interaction.judge_status == "running":
            await live.update(interaction.with_status("pending", error_message=None))
        ids.append(interaction.id)

    sem = asyncio.Semaphore(max(1, concurrency))

    async def _pump() -> None:
        async def _one(interaction_id: uuid.UUID) -> None:
            async with sem:
                await schedule_live_score(interaction_id)

        await asyncio.gather(*(_one(i) for i in ids))

    # Do not block lifespan on LLM scoring; run in the background.
    spawn(_pump(), name="requeue-live-scores")
    logger.info("Re-queued %s unfinished live interaction score(s)", len(ids))
    return len(ids)


async def recover_scoring_after_restart() -> None:
    """Lifespan hook: fail stuck experiments; re-queue unfinished live scores."""
    from opengrade_server.infrastructure.db import try_get_session_factory
    from opengrade_server.infrastructure.repositories import (
        SqlAlchemyEvaluationRunRepository,
        SqlAlchemyExperimentRepository,
        SqlAlchemyLiveInteractionRepository,
    )

    factory = try_get_session_factory()
    if factory is None:
        return

    async with factory() as session:
        experiments = SqlAlchemyExperimentRepository(session)
        runs = SqlAlchemyEvaluationRunRepository(session)
        live = SqlAlchemyLiveInteractionRepository(session)
        try:
            await fail_stuck_experiments(experiments, runs)
        except Exception:
            logger.exception("Failed to recover stuck experiments on startup")
        try:
            await requeue_unfinished_live_scores(live)
        except Exception:
            logger.exception("Failed to re-queue live scores on startup")
