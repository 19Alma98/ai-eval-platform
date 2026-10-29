import { apiGet } from "./client";
import type { ProductionMonitoring, ReleaseFacets, ReleaseFilter, VersionSummary } from "./types";

function rangeParams(since: string, until: string | undefined, filter?: ReleaseFilter) {
  const params = new URLSearchParams({ since });
  if (until) params.set("until", until);
  if (filter?.environment) params.set("environment", filter.environment);
  if (filter?.version) params.set("version", filter.version);
  return params.toString();
}

export function getMonitoring(
  projectId: string,
  since: string,
  until?: string,
  filter?: ReleaseFilter,
) {
  return apiGet<ProductionMonitoring>(
    `/api/v1/projects/${projectId}/monitoring?${rangeParams(since, until, filter)}`,
  );
}

export function getReleaseFacets(projectId: string, since: string, until?: string) {
  return apiGet<ReleaseFacets>(
    `/api/v1/projects/${projectId}/monitoring/facets?${rangeParams(since, until)}`,
  );
}

export function getVersionSummaries(
  projectId: string,
  since: string,
  until?: string,
  environment?: string | null,
) {
  return apiGet<VersionSummary[]>(
    `/api/v1/projects/${projectId}/monitoring/versions?${rangeParams(since, until, { environment })}`,
  );
}
