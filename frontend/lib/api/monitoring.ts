import { apiGet } from "./client";
import type { ProductionMonitoring } from "./types";

export function getMonitoring(projectId: string, since: string, until?: string) {
  const params = new URLSearchParams({ since });
  if (until) params.set("until", until);
  return apiGet<ProductionMonitoring>(
    `/api/v1/projects/${projectId}/monitoring?${params.toString()}`,
  );
}
