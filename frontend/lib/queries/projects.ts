import { listProjects } from "@/lib/api/projects";

export const projectsQueryKey = ["projects"] as const;

export function projectsQueryOptions() {
  return {
    queryKey: projectsQueryKey,
    queryFn: listProjects,
  } as const;
}
