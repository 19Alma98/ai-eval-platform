"use client";

import { useQuery } from "@tanstack/react-query";
import { getMonitoring } from "@/lib/api/monitoring";

export function monitoringQueryKey(projectId: string, since: string, until: string) {
  return ["monitoring", projectId, since, until] as const;
}

export function useMonitoring(projectId: string | null, since: string, until: string) {
  return useQuery({
    queryKey: monitoringQueryKey(projectId ?? "", since, until),
    queryFn: () => getMonitoring(projectId!, since, until),
    enabled: Boolean(projectId),
  });
}
