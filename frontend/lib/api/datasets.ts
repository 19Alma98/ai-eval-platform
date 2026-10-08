import { apiGet, apiPost, throwApiError } from "./client";
import type {
  Dataset,
  DatasetDetail,
  ImportDatasetItemsResult,
  TaskType,
} from "./types";

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

export async function importDatasetItems(
  datasetId: string,
  file: File,
  format?: string | null,
): Promise<ImportDatasetItemsResult> {
  const form = new FormData();
  form.append("file", file);
  const qs =
    format != null && format !== ""
      ? `?format=${encodeURIComponent(format)}`
      : "";
  const res = await fetch(
    `/api/v1/datasets/${encodeURIComponent(datasetId)}/items/import${qs}`,
    {
      method: "POST",
      body: form,
    },
  );
  if (!res.ok) await throwApiError(res);
  return res.json() as Promise<ImportDatasetItemsResult>;
}
