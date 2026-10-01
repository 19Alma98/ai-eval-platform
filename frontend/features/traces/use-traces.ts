"use client";

import { useQuery } from "@tanstack/react-query";
import { listTraces } from "@/lib/api/traces";

export type TracesFilters = {
  status?: string;
  start?: string;
  end?: string;
  cursor?: string;
  limit?: number;
};

export function tracesQueryKey(projectId: string, filters: TracesFilters) {
  return ["traces", projectId, filters] as const;
}

export function tracesQueryOptions(projectId: string, filters: TracesFilters) {
  return {
    queryKey: tracesQueryKey(projectId, filters),
    queryFn: () => listTraces(projectId, filters),
  } as const;
}

export function useTraces(projectId: string | null, filters: TracesFilters) {
  const key = projectId ?? "";
  return useQuery({
    ...tracesQueryOptions(key, filters),
    enabled: Boolean(projectId),
  });
}
