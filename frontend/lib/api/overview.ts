import { apiGet } from "./client";
import type { ProjectOverview } from "./types";

export function getOverview(
  projectId: string,
  since: string,
  until?: string,
) {
  const q = new URLSearchParams({ since });
  if (until) q.set("until", until);
  return apiGet<ProjectOverview>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/overview?${q}`,
  );
}
