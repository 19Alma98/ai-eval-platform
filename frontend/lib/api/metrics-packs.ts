import { apiGet, apiPost, apiPut } from "./client";
import type { MetricsPack, ReplaceMetricsPackBody } from "./types";

export function getMetricsPack(projectId: string) {
  return apiGet<MetricsPack>(`/api/v1/projects/${projectId}/metrics-pack`);
}

export function replaceMetricsPack(
  projectId: string,
  body: ReplaceMetricsPackBody,
) {
  return apiPut<MetricsPack>(
    `/api/v1/projects/${projectId}/metrics-pack`,
    body,
  );
}

export function ensureMetricsPack(projectId: string) {
  return apiPost<MetricsPack>(
    `/api/v1/projects/${projectId}/metrics-pack/ensure`,
    {},
  );
}
