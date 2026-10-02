import { apiGet, apiPost } from "./client";
import type {
  EvaluateResponse,
  Experiment,
  ExperimentCompareResponse,
  ExperimentSummary,
} from "./types";

export function listExperiments(projectId: string) {
  return apiGet<Experiment[]>(`/api/v1/projects/${projectId}/experiments`);
}

export function createExperiment(
  projectId: string,
  body: {
    name: string;
    dataset_id: string;
    model_config?: Record<string, unknown>;
    application_version?: string | null;
    baseline_experiment_id?: string | null;
  },
) {
  return apiPost<Experiment>(
    `/api/v1/projects/${projectId}/experiments`,
    body,
  );
}

export function getExperiment(id: string) {
  return apiGet<Experiment>(`/api/v1/experiments/${id}`);
}

export function summarizeExperiment(id: string) {
  return apiGet<ExperimentSummary>(`/api/v1/experiments/${id}/summary`);
}

export function compareExperiments(experimentId: string, baselineId: string) {
  return apiGet<ExperimentCompareResponse>(
    `/api/v1/experiments/${experimentId}/compare/${baselineId}`,
  );
}

export function evaluateExperiment(
  id: string,
  body: { evaluator_ids: string[] },
) {
  return apiPost<EvaluateResponse>(`/api/v1/experiments/${id}/evaluate`, body);
}
