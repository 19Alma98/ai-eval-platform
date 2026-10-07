import { apiGet, apiPost } from "./client";
import type { DatasetItem, LiveInteraction, LiveReview } from "./types";

export function listLiveInteractions(
  projectId: string,
  opts?: {
    judgeStatus?: string;
    search?: string;
    failedOnly?: boolean;
    limit?: number;
  },
) {
  const params = new URLSearchParams();
  if (opts?.judgeStatus) params.set("judge_status", opts.judgeStatus);
  if (opts?.search) params.set("search", opts.search);
  if (opts?.failedOnly) params.set("failed_only", "true");
  if (opts?.limit != null) params.set("limit", String(opts.limit));
  const qs = params.toString();
  return apiGet<LiveInteraction[]>(
    `/api/v1/projects/${projectId}/live-interactions${qs ? `?${qs}` : ""}`,
  );
}

export function getLiveInteraction(id: string) {
  return apiGet<LiveInteraction>(`/api/v1/live-interactions/${id}`);
}

export function reviewLiveInteraction(
  id: string,
  body: { verdict: string; note?: string; reviewer?: string },
) {
  return apiPost<LiveReview>(`/api/v1/live-interactions/${id}/review`, body);
}

export function promoteLiveInteraction(
  id: string,
  body: { dataset_id: string; expected_output?: unknown },
) {
  return apiPost<DatasetItem>(
    `/api/v1/live-interactions/${id}/promote`,
    body,
  );
}

export function rescoreLiveInteraction(id: string) {
  return apiPost<LiveInteraction>(
    `/api/v1/live-interactions/${id}/rescore`,
    {},
  );
}
