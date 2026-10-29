"""Retention of production data.

Each project keeps ``retention_days`` of production data (else the server's
``RETENTION_DAYS``; unset keeps everything). Older production traces (with their
spans), live interactions (with judge scores and reviews), trace scores and alert
events are deleted by a periodic job, or on demand. Evaluation data stays: traces
bound to an experiment run and traces a test case was built from are never purged,
and datasets, experiments and their results are untouched.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol

from opengrade_server.application.projects import ProjectNotFoundError
from opengrade_server.domain.project import Project
from opengrade_server.domain.repositories import ProjectRepository
from opengrade_server.domain.trace import Trace
from opengrade_server.tracing.run_binding import extract_run_binding

logger = logging.getLogger(__name__)

MAX_RETENTION_DAYS = 36500
_BATCH = 500


class RetentionValidationError(ValueError):
    pass


class RetentionRepository(Protocol):
    async def old_traces(
        self,
        project_id: uuid.UUID,
        *,
        before: datetime,
        after: tuple[datetime, uuid.UUID] | None = None,
        limit: int = 500,
    ) -> list[Trace]: ...

    async def dataset_trace_ids(self, project_id: uuid.UUID) -> set[str]: ...

    async def delete_traces(self, trace_pks: list[uuid.UUID]) -> int: ...

    async def purge_rows(
        self, project_id: uuid.UUID, *, before: datetime, dry_run: bool
    ) -> dict[str, int]: ...


def effective_retention_days(project: Project, default_days: int | None) -> int | None:
    return project.retention_days if project.retention_days is not None else default_days


@dataclass(frozen=True, slots=True)
class PurgeReport:
    project_id: uuid.UUID
    retention_days: int | None
    cutoff: datetime | None
    dry_run: bool
    traces: int = 0
    traces_kept: int = 0
    rows: dict[str, int] = field(default_factory=dict)
    # The project's own setting (``retention_days`` is the effective one).
    project_days: int | None = None


class PurgeProductionData:
    def __init__(
        self,
        projects: ProjectRepository,
        retention: RetentionRepository,
        *,
        default_days: int | None = None,
    ) -> None:
        self._projects = projects
        self._retention = retention
        self._default_days = default_days

    async def execute(
        self,
        project_id: uuid.UUID,
        *,
        dry_run: bool = False,
        now: datetime | None = None,
    ) -> PurgeReport:
        project = await self._projects.get_by_id(project_id)
        if project is None:
            raise ProjectNotFoundError(project_id)
        days = effective_retention_days(project, self._default_days)
        if days is None:
            return PurgeReport(project_id, None, None, dry_run)  # keep forever
        cutoff = (now or datetime.now(UTC)) - timedelta(days=days)
        keep_ids = await self._retention.dataset_trace_ids(project_id)
        deleted = kept = 0
        after: tuple[datetime, uuid.UUID] | None = None
        while True:
            batch = await self._retention.old_traces(
                project_id, before=cutoff, after=after, limit=_BATCH
            )
            if not batch:
                break
            doomed = [
                t.id for t in batch if t.trace_id not in keep_ids and extract_run_binding(t) is None
            ]
            kept += len(batch) - len(doomed)
            if dry_run:
                deleted += len(doomed)
            else:
                deleted += await self._retention.delete_traces(doomed)
            # Kept traces stay in place, so page past the last one seen.
            after = (batch[-1].start_time, batch[-1].id)
        rows = await self._retention.purge_rows(project_id, before=cutoff, dry_run=dry_run)
        return PurgeReport(
            project_id, days, cutoff, dry_run, deleted, kept, rows, project.retention_days
        )


class SetProjectRetention:
    def __init__(self, projects: ProjectRepository) -> None:
        self._projects = projects

    async def execute(self, project_id: uuid.UUID, days: int | None) -> Project:
        if days is not None and not 1 <= days <= MAX_RETENTION_DAYS:
            raise RetentionValidationError(
                f"retention_days must be between 1 and {MAX_RETENTION_DAYS}, or null"
            )
        project = await self._projects.set_retention_days(project_id, days)
        if project is None:
            raise ProjectNotFoundError(project_id)
        return project


async def purge_all_projects(
    projects: ProjectRepository, retention: RetentionRepository, default_days: int | None
) -> list[PurgeReport]:
    use_case = PurgeProductionData(projects, retention, default_days=default_days)
    reports = []
    for project in await projects.list_all():
        if effective_retention_days(project, default_days) is None:
            continue
        report = await use_case.execute(project.id)
        if report.traces or any(report.rows.values()):
            logger.info(
                "Retention purged project %s: %s traces, %s",
                project.slug,
                report.traces,
                report.rows,
            )
        reports.append(report)
    return reports


async def run_retention_loop(interval_hours: float, *, first_delay_seconds: float = 60.0) -> None:
    """Purge every project with a retention period, then every ``interval_hours``."""
    from opengrade_server.config import get_settings
    from opengrade_server.infrastructure.db import try_get_session_factory
    from opengrade_server.infrastructure.repositories import (
        SqlAlchemyProjectRepository,
        SqlAlchemyRetentionRepository,
    )

    delay = first_delay_seconds
    while True:
        await asyncio.sleep(delay)
        delay = interval_hours * 3600
        factory = try_get_session_factory()
        if factory is None:
            continue
        try:
            async with factory() as session:
                await purge_all_projects(
                    SqlAlchemyProjectRepository(session),
                    SqlAlchemyRetentionRepository(session),
                    get_settings().retention_days,
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Retention purge failed")
