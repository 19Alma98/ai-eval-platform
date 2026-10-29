from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status

from opengrade_server.api.deps import (
    get_production_monitoring,
    get_production_versions,
    get_release_facets,
)
from opengrade_server.api.schemas import (
    LatencyPercentilesResponse,
    MetricBucketResponse,
    MetricMonitorResponse,
    ProductionMonitoringResponse,
    ReleaseFacetsResponse,
    ReleaseFacetValueResponse,
    TrafficBucketResponse,
    VersionMetricResponse,
    VersionSummaryResponse,
)
from opengrade_server.application.monitoring import (
    GetProductionMonitoring,
    GetProductionVersions,
    GetReleaseFacets,
    LatencyPercentiles,
    ProductionMonitoring,
)
from opengrade_server.application.projects import ProjectNotFoundError

router = APIRouter(prefix="/api/v1/projects", tags=["monitoring"])


def _latency(value: LatencyPercentiles) -> LatencyPercentilesResponse:
    return LatencyPercentilesResponse(p50_ms=value.p50_ms, p90_ms=value.p90_ms, p99_ms=value.p99_ms)


def _to_response(result: ProductionMonitoring) -> ProductionMonitoringResponse:
    return ProductionMonitoringResponse(
        since=result.since,
        until=result.until,
        bucket_seconds=result.bucket_seconds,
        n_traces=result.n_traces,
        n_errors=result.n_errors,
        latency=_latency(result.latency),
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        total_tokens=result.total_tokens,
        cost_usd=result.cost_usd,
        traces_truncated=result.traces_truncated,
        n_needs_review=result.n_needs_review,
        traffic=[
            TrafficBucketResponse(
                bucket_start=b.bucket_start,
                n_traces=b.n_traces,
                n_errors=b.n_errors,
                latency=_latency(b.latency),
                total_tokens=b.total_tokens,
                cost_usd=b.cost_usd,
            )
            for b in result.traffic
        ],
        metrics=[
            MetricMonitorResponse(
                name=m.name,
                source=m.source,
                n=m.n,
                mean=m.mean,
                fail_rate=m.fail_rate,
                threshold=m.threshold,
                histogram_edges=m.histogram_edges,
                histogram_counts=m.histogram_counts,
                series=[
                    MetricBucketResponse(
                        bucket_start=b.bucket_start, n=b.n, mean=b.mean, fail_rate=b.fail_rate
                    )
                    for b in m.series
                ],
            )
            for m in result.metrics
        ],
    )


def _range(since: datetime, until: datetime | None) -> tuple[datetime, datetime | None]:
    if since.tzinfo is None:
        since = since.replace(tzinfo=UTC)
    if until is not None and until.tzinfo is None:
        until = until.replace(tzinfo=UTC)
    if until is not None and until <= since:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="until must be after since"
        )
    return since, until


@router.get("/{project_id}/monitoring", response_model=ProductionMonitoringResponse)
async def get_production_monitoring_route(
    project_id: uuid.UUID,
    since: datetime = Query(...),
    until: datetime | None = Query(None),
    environment: str | None = Query(None, max_length=200),
    version: str | None = Query(None, max_length=200),
    use_case: GetProductionMonitoring = Depends(get_production_monitoring),
) -> ProductionMonitoringResponse:
    since, until = _range(since, until)
    try:
        result = await use_case.execute(
            project_id, since=since, until=until, environment=environment, version=version
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _to_response(result)


@router.get("/{project_id}/monitoring/facets", response_model=ReleaseFacetsResponse)
async def get_release_facets_route(
    project_id: uuid.UUID,
    since: datetime = Query(...),
    until: datetime | None = Query(None),
    use_case: GetReleaseFacets = Depends(get_release_facets),
) -> ReleaseFacetsResponse:
    """Environments and versions seen in the range (for filter pickers)."""
    since, until = _range(since, until)
    try:
        facets = await use_case.execute(project_id, since=since, until=until)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return ReleaseFacetsResponse(
        environments=[
            ReleaseFacetValueResponse(value=v, n_traces=n) for v, n in facets["environment"]
        ],
        versions=[ReleaseFacetValueResponse(value=v, n_traces=n) for v, n in facets["version"]],
    )


@router.get("/{project_id}/monitoring/versions", response_model=list[VersionSummaryResponse])
async def get_production_versions_route(
    project_id: uuid.UUID,
    since: datetime = Query(...),
    until: datetime | None = Query(None),
    environment: str | None = Query(None, max_length=200),
    use_case: GetProductionVersions = Depends(get_production_versions),
) -> list[VersionSummaryResponse]:
    """Production health per release (``service.version``), up to 10, most traffic first."""
    since, until = _range(since, until)
    try:
        rows = await use_case.execute(project_id, since=since, until=until, environment=environment)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    out: list[VersionSummaryResponse] = []
    for row in rows:
        m = row.monitoring
        out.append(
            VersionSummaryResponse(
                version=row.version,
                n_traces=m.n_traces,
                n_errors=m.n_errors,
                error_rate=m.n_errors / m.n_traces if m.n_traces else None,
                latency=_latency(m.latency),
                total_tokens=m.total_tokens,
                cost_usd=m.cost_usd,
                cost_per_trace_usd=m.cost_usd / m.n_traces if m.n_traces else None,
                traces_truncated=m.traces_truncated,
                metrics=[
                    VersionMetricResponse(
                        name=x.name, source=x.source, n=x.n, mean=x.mean, fail_rate=x.fail_rate
                    )
                    for x in m.metrics
                ],
            )
        )
    return out
