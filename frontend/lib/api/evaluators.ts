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

export type EvaluatorPreview = {
  score: number | null;
  label: string | null;
  explanation: string | null;
  metadata: Record<string, unknown>;
  system_prompt: string | null;
};

/** Run an evaluator config on one sample without saving anything (calls the judge). */
export function previewEvaluator(
  projectId: string,
  body: {
    config: Record<string, unknown>;
    sample: {
      input?: unknown;
      output: unknown;
      expected_output?: unknown;
      documents?: Record<string, unknown>[] | null;
      metadata?: Record<string, unknown>;
    };
  },
) {
  return apiPost<EvaluatorPreview>(
    `/api/v1/projects/${projectId}/evaluators/preview`,
    body,
  );
}
