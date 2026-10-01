import { apiGet, apiPost } from "./client";
import type { Dataset, DatasetItem } from "./types";

export function listDatasets(projectId: string) {
  return apiGet<Dataset[]>(`/api/v1/projects/${projectId}/datasets`);
}

export function createDataset(
  projectId: string,
  body: { name: string; description?: string; version?: number },
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
