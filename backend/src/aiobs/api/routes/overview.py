from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status

from aiobs.api.deps import get_project_overview as get_project_overview_use_case
from aiobs.api.schemas import (
    CalibrationAlertResponse,
    LiveAttentionItemResponse,
    LiveOverviewResponse,
    LiveSeriesBucketResponse,
    OfflineOverviewResponse,
    OverviewCompareMetricResponse,
    OverviewCompareResponse,
    OverviewExperimentRefResponse,
    OverviewMetricsSetRefResponse,
    OverviewRegressionResponse,
    ProjectOverviewResponse,
)
from aiobs.application.project_overview import GetProjectOverview, ProjectOverviewResult
from aiobs.application.projects import ProjectNotFoundError

router = APIRouter(prefix="/api/v1/projects", tags=["overview"])


def _to_response(result: ProjectOverviewResult) -> ProjectOverviewResponse:
    live = result.live
    offline = result.offline
    metrics_set = offline.metrics_set
    latest = offline.latest_experiment
    compare = offline.compare
    return ProjectOverviewResponse(
        generated_at=result.generated_at,
        since=result.since,
        until=result.until,
        live=LiveOverviewResponse(
            n_interactions=live.n_interactions,
            n_failed=live.n_failed,
            n_pending=live.n_pending,
            mean_score=live.mean_score,
            fail_rate=live.fail_rate,
            series=[
                LiveSeriesBucketResponse(
                    bucket_start=b.bucket_start,
                    n=b.n,
                    mean_score=b.mean_score,
                    fail_rate=b.fail_rate,
                )
                for b in live.series
            ],
            attention=[
                LiveAttentionItemResponse(
                    interaction_id=a.interaction_id,
                    question=a.question,
                    created_at=a.created_at,
                    reason=a.reason,
                )
                for a in live.attention
            ],
        ),
        offline=OfflineOverviewResponse(
            n_datasets=offline.n_datasets,
            metrics_set=(
                OverviewMetricsSetRefResponse(
                    id=metrics_set.id,
                    name=metrics_set.name,
                    version=metrics_set.version,
                    is_default=metrics_set.is_default,
                )
                if metrics_set is not None
                else None
            ),
            reference_threshold=offline.reference_threshold,
            latest_experiment=(
                OverviewExperimentRefResponse(
                    id=latest.id,
                    name=latest.name,
                    status=latest.status,
                    created_at=latest.created_at,
                    baseline_experiment_id=latest.baseline_experiment_id,
                )
                if latest is not None
                else None
            ),
            release_ready=offline.release_ready,
            compare=(
                OverviewCompareResponse(
                    candidate_experiment_id=compare.candidate_experiment_id,
                    baseline_experiment_id=compare.baseline_experiment_id,
                    metrics=[
                        OverviewCompareMetricResponse(
                            name=m.name,
                            metric=m.metric,
                            candidate=m.candidate,
                            baseline=m.baseline,
                            delta=m.delta,
                            status=m.status,
                        )
                        for m in compare.metrics
                    ],
                )
                if compare is not None
                else None
            ),
            regressions=[
                OverviewRegressionResponse(name=r.name, delta=r.delta, status=r.status)
                for r in offline.regressions
            ],
        ),
        calibration_alerts=[
            CalibrationAlertResponse(
                kind=a.kind,
                agreement_rate=a.agreement_rate,
                n_reviewed=a.n_reviewed,
            )
            for a in result.calibration_alerts
        ],
        warnings=list(result.warnings),
    )


@router.get("/{project_id}/overview", response_model=ProjectOverviewResponse)
async def get_project_overview(
    project_id: uuid.UUID,
    since: datetime = Query(...),
    until: datetime | None = Query(None),
    use_case: GetProjectOverview = Depends(get_project_overview_use_case),
) -> ProjectOverviewResponse:
    try:
        result = await use_case.execute(project_id, since=since, until=until)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _to_response(result)
