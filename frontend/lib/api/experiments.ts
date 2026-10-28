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

const TERMINAL_EXPERIMENT_STATUSES = new Set([
  "completed",
  "failed",
  "cancelled",
]);

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitUntilExperimentTerminal(
  experimentId: string,
  {
    pollIntervalMs = 2000,
    timeoutMs = 600_000,
  }: { pollIntervalMs?: number; timeoutMs?: number } = {},
): Promise<Experiment> {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const experiment = await getExperiment(experimentId);
    if (TERMINAL_EXPERIMENT_STATUSES.has(experiment.status.toLowerCase())) {
      return experiment;
    }
    if (Date.now() >= deadline) {
      throw new Error(
        `Timed out waiting for experiment scoring (status=${experiment.status}).`,
      );
    }
    await sleep(pollIntervalMs);
  }
}

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

export function summarizeProjectExperiments(
  projectId: string,
  experimentIds?: string[],
) {
  const params = new URLSearchParams();
  for (const id of experimentIds ?? []) params.append("experiment_ids", id);
  const qs = params.toString();
  return apiGet<ExperimentSummary[]>(
    `/api/v1/projects/${projectId}/experiments/summaries${qs ? `?${qs}` : ""}`,
  );
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

export function listExperimentRuns(experimentId: string) {
  return apiGet<EvaluationRun[]>(
    `/api/v1/experiments/${experimentId}/runs`,
  );
}

export async function evaluateExperiment(
  id: string,
  body: { evaluator_ids: string[] },
): Promise<EvaluateResponse> {
  await apiPost<Experiment>(`/api/v1/experiments/${id}/evaluate`, body);
  const experiment = await waitUntilExperimentTerminal(id);
  const runs = await listExperimentRuns(id);
  return { experiment, runs };
}

export async function evaluatePack(
  experimentId: string,
  body?: { metrics_set_id?: string; save_as_default?: boolean },
): Promise<EvaluateResponse> {
  await apiPost<Experiment>(
    `/api/v1/experiments/${experimentId}/evaluate-pack`,
    body ?? {},
  );
  const experiment = await waitUntilExperimentTerminal(experimentId);
  const runs = await listExperimentRuns(experimentId);
  return { experiment, runs };
}

export function getEvaluationRun(runId: string) {
  return apiGet<EvaluationRun>(`/api/v1/evaluation-runs/${runId}`);
}

export function listExperimentOutputs(experimentId: string) {
  return apiGet<ExperimentItemOutput[]>(
    `/api/v1/experiments/${experimentId}/outputs`,
  );
}
