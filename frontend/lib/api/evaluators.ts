import { apiGet, apiPost } from "./client";
import type { Evaluator } from "./types";

export function listEvaluators(projectId: string) {
  return apiGet<Evaluator[]>(`/api/v1/projects/${projectId}/evaluators`);
}

export function createEvaluator(
  projectId: string,
  body: {
    name: string;
    type: string;
    config: Record<string, unknown>;
    version?: number;
  },
) {
  return apiPost<Evaluator>(
    `/api/v1/projects/${projectId}/evaluators`,
    body,
  );
}
