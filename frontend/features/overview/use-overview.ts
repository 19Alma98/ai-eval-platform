"use client";

import { useQuery } from "@tanstack/react-query";
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
  });
}
