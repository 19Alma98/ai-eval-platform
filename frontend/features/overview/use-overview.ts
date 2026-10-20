"use client";

import { useQuery } from "@tanstack/react-query";
import { keepPreviousInProject } from "@/lib/queries/keep-previous";
import { getOverview } from "@/lib/api/overview";

export function overviewQueryKey(
  projectId: string,
  since: string,
  until?: string,
) {
  return ["overview", projectId, since, until ?? null] as const;
}

export function useOverview(
  projectId: string | null | undefined,
  since: string,
  until?: string,
) {
  return useQuery({
    queryKey: overviewQueryKey(projectId ?? "", since, until),
    queryFn: () => getOverview(projectId!, since, until),
    enabled: Boolean(projectId),
    // A refresh moves the time window; keep the old numbers until the new ones arrive.
    placeholderData: keepPreviousInProject(projectId ?? ""),
  });
}
