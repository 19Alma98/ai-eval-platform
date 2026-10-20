import type { Project } from "@/lib/api/types";

/**
 * What to do when the selected project (URL or localStorage) is not in the project list,
 * e.g. it was deleted in another tab: switch to the first project, or clear the selection.
 */
export function projectFallback(
  projectId: string | null,
  projects: Pick<Project, "id" | "name">[] | undefined,
): { action: "keep" } | { action: "switch"; to: Pick<Project, "id" | "name"> } | { action: "clear" } {
  if (!projectId || !projects) return { action: "keep" };
  if (projects.some((p) => p.id === projectId)) return { action: "keep" };
  const first = projects[0];
  return first ? { action: "switch", to: first } : { action: "clear" };
}
