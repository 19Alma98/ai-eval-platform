import { apiGet, apiPost } from "./client";
import type { Project } from "./types";

export function listProjects() {
  return apiGet<Project[]>("/api/v1/projects");
}

export function createProject(body: { name: string; slug?: string }) {
  return apiPost<Project>("/api/v1/projects", body);
}
