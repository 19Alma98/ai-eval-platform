import { apiDelete, apiGet, apiPut } from "./client";
import type { ExperimentAlias, ExperimentAliasEvent } from "./types";

export function listExperimentAliases(projectId: string) {
  return apiGet<ExperimentAlias[]>(
    `/api/v1/projects/${projectId}/experiment-aliases`,
  );
}

export type SetExperimentAliasBody = {
  experiment_id: string;
  note?: string | null;
  force?: boolean;
};

export function setExperimentAlias(
  projectId: string,
  alias: string,
  body: SetExperimentAliasBody,
) {
  return apiPut<ExperimentAlias>(
    `/api/v1/projects/${projectId}/experiment-aliases/${encodeURIComponent(alias)}`,
    {
      experiment_id: body.experiment_id,
      note: body.note ?? null,
      force: body.force ?? false,
    },
  );
}

export function listExperimentAliasHistory(
  projectId: string,
  alias: string,
  opts?: { limit?: number },
) {
  const params = new URLSearchParams();
  if (opts?.limit != null) params.set("limit", String(opts.limit));
  const qs = params.toString() ? `?${params.toString()}` : "";
  return apiGet<ExperimentAliasEvent[]>(
    `/api/v1/projects/${projectId}/experiment-aliases/${encodeURIComponent(alias)}/history${qs}`,
  );
}

export function deleteExperimentAlias(projectId: string, alias: string) {
  return apiDelete(
    `/api/v1/projects/${projectId}/experiment-aliases/${encodeURIComponent(alias)}`,
  );
}
