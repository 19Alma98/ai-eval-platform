import { apiGet } from "./client";
import type { TraceDetail } from "./types";

export function getTrace(projectId: string, traceId: string) {
  return apiGet<TraceDetail>(
    `/api/v1/projects/${projectId}/traces/${encodeURIComponent(traceId)}`,
  );
}
