import { apiGet } from "./client";
import type { Project } from "./types";

export function listProjects() {
  return apiGet<Project[]>("/api/v1/projects");
}
