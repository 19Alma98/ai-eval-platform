import { apiGet } from "./client";
import type { TraceDetail, TraceFacets, TraceListResponse } from "./types";

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
    userId?: string | null;
    sessionId?: string | null;
    tags?: string[];
    metadata?: string[]; // "key:value"
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
  if (opts?.userId) params.set("user_id", opts.userId);
  if (opts?.sessionId) params.set("session_id", opts.sessionId);
  for (const tag of opts?.tags ?? []) params.append("tag", tag);
  for (const pair of opts?.metadata ?? []) params.append("metadata", pair);
  const qs = params.toString();
  return apiGet<TraceListResponse>(
    `/api/v1/projects/${projectId}/traces${qs ? `?${qs}` : ""}`,
  );
}

export function getTraceFacets(projectId: string) {
  return apiGet<TraceFacets>(`/api/v1/projects/${projectId}/traces/facets`);
}
