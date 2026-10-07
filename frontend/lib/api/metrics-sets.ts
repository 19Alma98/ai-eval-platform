import { apiGet, apiPatch, apiPost, throwApiError } from "./client";
import type {
  CreateMetricsSetBody,
  MetricsSet,
  MetricsSetSummary,
  PatchMetricsSetBody,
} from "./types";

export function listMetricsSets(projectId: string) {
  return apiGet<MetricsSetSummary[]>(
    `/api/v1/projects/${projectId}/metrics-sets`,
  );
}

export function getMetricsSet(metricsSetId: string) {
  return apiGet<MetricsSet>(`/api/v1/metrics-sets/${metricsSetId}`);
}

export function createMetricsSet(projectId: string, body: CreateMetricsSetBody) {
  return apiPost<MetricsSet>(
    `/api/v1/projects/${projectId}/metrics-sets`,
    body,
  );
}

export function patchMetricsSet(
  metricsSetId: string,
  body: PatchMetricsSetBody,
) {
  return apiPatch<MetricsSet>(`/api/v1/metrics-sets/${metricsSetId}`, body);
}

export function versionMetricsSet(metricsSetId: string, body?: { description?: string | null }) {
  return apiPost<MetricsSet>(
    `/api/v1/metrics-sets/${metricsSetId}/version`,
    body ?? {},
  );
}

export async function deleteMetricsSetEntry(
  metricsSetId: string,
  entryId: string,
) {
  const res = await fetch(
    `/api/v1/metrics-sets/${encodeURIComponent(metricsSetId)}/entries/${encodeURIComponent(entryId)}`,
    {
      method: "DELETE",
      headers: { Accept: "application/json" },
    },
  );
  if (!res.ok) await throwApiError(res);
  return res.json() as Promise<MetricsSet>;
}
