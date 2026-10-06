import { apiGet, apiPost } from "./client";
import type {
  EvaluateResponse,
  EvaluationRun,
  Experiment,
  ExperimentCompareResponse,
  ExperimentItemOutput,
  ExperimentSummary,
  ItemComparisonResponse,
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
    app_config_id?: string;
    app_config_alias?: string;
    version?: string | null;
    baseline_experiment_id?: string | null;
    metrics_set_id?: string | null;
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

export function compareExperimentItems(
  experimentId: string,
  baselineId: string,
  opts?: { evaluatorId?: string; regressionsOnly?: boolean },
) {
  const params = new URLSearchParams();
  if (opts?.evaluatorId) params.set("evaluator_id", opts.evaluatorId);
  if (opts?.regressionsOnly) params.set("regressions_only", "true");
  const qs = params.toString();
  return apiGet<ItemComparisonResponse>(
    `/api/v1/experiments/${experimentId}/compare/${baselineId}/items${qs ? `?${qs}` : ""}`,
  );
}

export function evaluateExperiment(
  id: string,
  body: { evaluator_ids: string[] },
) {
  return apiPost<EvaluateResponse>(`/api/v1/experiments/${id}/evaluate`, body);
}

export function evaluatePack(
  experimentId: string,
  body?: { metrics_set_id?: string; save_as_default?: boolean },
) {
  return apiPost<EvaluateResponse>(
    `/api/v1/experiments/${experimentId}/evaluate-pack`,
    body ?? {},
  );
}

export function getEvaluationRun(runId: string) {
  return apiGet<EvaluationRun>(`/api/v1/evaluation-runs/${runId}`);
}

export function listExperimentOutputs(experimentId: string) {
  return apiGet<ExperimentItemOutput[]>(
    `/api/v1/experiments/${experimentId}/outputs`,
  );
}
