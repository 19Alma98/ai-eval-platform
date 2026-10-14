from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status

from opengrade_server.api.deps import get_production_monitoring
from opengrade_server.api.schemas import (
    LatencyPercentilesResponse,
    MetricBucketResponse,
    MetricMonitorResponse,
    ProductionMonitoringResponse,
    TrafficBucketResponse,
)
from opengrade_server.application.monitoring import (
    GetProductionMonitoring,
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


@router.get("/{project_id}/monitoring", response_model=ProductionMonitoringResponse)
async def get_production_monitoring_route(
    project_id: uuid.UUID,
    since: datetime = Query(...),
    until: datetime | None = Query(None),
    use_case: GetProductionMonitoring = Depends(get_production_monitoring),
) -> ProductionMonitoringResponse:
    if until is not None and until <= since:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="until must be after since"
        )
    try:
        result = await use_case.execute(project_id, since=since, until=until)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _to_response(result)
