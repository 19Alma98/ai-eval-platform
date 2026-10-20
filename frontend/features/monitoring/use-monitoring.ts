"use client";

import { useQuery } from "@tanstack/react-query";
import { keepPreviousInProject } from "@/lib/queries/keep-previous";
import { getMonitoring } from "@/lib/api/monitoring";

export function monitoringQueryKey(projectId: string, since: string, until: string) {
  return ["monitoring", projectId, since, until] as const;
}

export function useMonitoring(projectId: string | null, since: string, until: string) {
  return useQuery({
    queryKey: monitoringQueryKey(projectId ?? "", since, until),
    queryFn: () => getMonitoring(projectId!, since, until),
    enabled: Boolean(projectId),
    // A refresh moves the time window; keep the old numbers until the new ones arrive.
    placeholderData: keepPreviousInProject(projectId ?? ""),
  });
}
