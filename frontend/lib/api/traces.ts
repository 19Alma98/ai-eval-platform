import { apiGet } from "./client";
import type { TraceDetail, TraceListResponse } from "./types";

export function getTrace(projectId: string, traceId: string) {
  return apiGet<TraceDetail>(
    `/api/v1/projects/${projectId}/traces/${encodeURIComponent(traceId)}`,
  );
}

export function listTraces(
  projectId: string,
  opts?: {
    status?: string;
    search?: string;
    since?: string;
    cursor?: string;
    limit?: number;
    environment?: string | null;
    version?: string | null;
  },
) {
  const params = new URLSearchParams();
  if (opts?.environment) params.set("environment", opts.environment);
  if (opts?.version) params.set("version", opts.version);
  if (opts?.status) params.set("status", opts.status);
  if (opts?.search) params.set("search", opts.search);
  if (opts?.since) params.set("since", opts.since);
  if (opts?.cursor) params.set("cursor", opts.cursor);
  if (opts?.limit != null) params.set("limit", String(opts.limit));
  const qs = params.toString();
  return apiGet<TraceListResponse>(
    `/api/v1/projects/${projectId}/traces${qs ? `?${qs}` : ""}`,
  );
}
