import { apiGet } from "./client";
import type { TraceDetail, TraceListResponse } from "./types";

export function listTraces(
  projectId: string,
  q: {
    status?: string;
    start?: string;
    end?: string;
    cursor?: string;
    limit?: number;
  },
) {
  const params = new URLSearchParams();
  if (q.status) params.set("status", q.status);
  if (q.start) params.set("start", q.start);
  if (q.end) params.set("end", q.end);
  if (q.cursor) params.set("cursor", q.cursor);
  if (q.limit) params.set("limit", String(q.limit));
  const qs = params.toString();
  return apiGet<TraceListResponse>(
    `/api/v1/projects/${projectId}/traces${qs ? `?${qs}` : ""}`,
  );
}

export function getTrace(projectId: string, traceId: string) {
  return apiGet<TraceDetail>(
    `/api/v1/projects/${projectId}/traces/${encodeURIComponent(traceId)}`,
  );
}
