import { apiPost } from "./client";
import type { ReleaseCheckResponse } from "./types";

export function postReleaseCheck(
  projectId: string,
  body: {
    experiment_id: string;
    baseline_experiment_id?: string | null;
    policy: Record<string, unknown>;
  },
) {
  return apiPost<ReleaseCheckResponse>(
    `/api/v1/projects/${projectId}/release-check`,
    body,
  );
}
