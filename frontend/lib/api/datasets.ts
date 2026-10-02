import { apiGet, apiPost } from "./client";
import type { Dataset, DatasetDetail, DatasetItem, TaskType } from "./types";

export function listTaskTypes() {
  return apiGet<TaskType[]>("/api/v1/task-types");
}

export function listDatasets(projectId: string, taskType?: string | null) {
  const qs =
    taskType != null && taskType !== ""
      ? `?task_type=${encodeURIComponent(taskType)}`
      : "";
  return apiGet<Dataset[]>(`/api/v1/projects/${projectId}/datasets${qs}`);
}

export function getDataset(datasetId: string) {
  return apiGet<DatasetDetail>(`/api/v1/datasets/${datasetId}`);
}

export function createDataset(
  projectId: string,
  body: {
    name: string;
    description?: string;
    version?: number;
    task_type?: string | null;
  },
) {
  return apiPost<Dataset>(`/api/v1/projects/${projectId}/datasets`, body);
}

export function addItemFromTrace(
  datasetId: string,
  body: {
    trace_id: string;
    source_span_id?: string;
    expected_output?: unknown;
    metadata?: Record<string, unknown>;
  },
) {
  return apiPost<DatasetItem>(
    `/api/v1/datasets/${datasetId}/items/from-trace`,
    body,
  );
}
