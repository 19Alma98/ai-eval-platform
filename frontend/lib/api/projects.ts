import { apiDelete, apiGet, apiPost, apiPut } from "./client";
import type { Project, ProjectRetention, PurgeReport } from "./types";

export function listProjects() {
  return apiGet<Project[]>("/api/v1/projects");
}

export function createProject(body: { name: string; slug?: string }) {
  return apiPost<Project>("/api/v1/projects", body);
}

export function deleteProject(projectId: string) {
  return apiDelete(`/api/v1/projects/${encodeURIComponent(projectId)}`);
}

export function getRetention(projectId: string) {
  return apiGet<ProjectRetention>(`/api/v1/projects/${encodeURIComponent(projectId)}/retention`);
}

export function setRetention(projectId: string, retentionDays: number | null) {
  return apiPut<ProjectRetention>(`/api/v1/projects/${encodeURIComponent(projectId)}/retention`, {
    retention_days: retentionDays,
  });
}

export function purgeNow(projectId: string) {
  return apiPost<PurgeReport>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/retention/purge`,
    {},
  );
}
