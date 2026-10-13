import { apiGet } from "./client";
import type { TraceScoreSummary } from "./types";

export function getTraceScoreSummary(projectId: string, since: string, until?: string) {
  const q = new URLSearchParams({ since });
  if (until) q.set("until", until);
  return apiGet<TraceScoreSummary>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/trace-scores/summary?${q}`,
  );
}
