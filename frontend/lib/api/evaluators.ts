import { apiGet } from "./client";
import type { Evaluator } from "./types";

export function listEvaluators(projectId: string) {
  return apiGet<Evaluator[]>(`/api/v1/projects/${projectId}/evaluators`);
}
