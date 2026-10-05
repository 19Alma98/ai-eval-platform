"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ensureMetricsPack,
  getMetricsPack,
  replaceMetricsPack,
} from "@/lib/api/metrics-packs";
import type { MetricsPackEntry } from "@/lib/api/types";

export function metricsPackQueryKey(projectId: string) {
  return ["metrics-pack", projectId] as const;
}

export function metricsPackQueryOptions(projectId: string) {
  return {
    queryKey: metricsPackQueryKey(projectId),
    queryFn: () => getMetricsPack(projectId),
  } as const;
}

export function useMetricsPack(projectId: string | null) {
  return useQuery({
    ...metricsPackQueryOptions(projectId ?? ""),
    enabled: Boolean(projectId),
    retry: (failureCount, error) => {
      if (
        error &&
        typeof error === "object" &&
        "status" in error &&
        (error as { status: number }).status === 404
      ) {
        return false;
      }
      return failureCount < 2;
    },
  });
}

export function useEnsureMetricsPack(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => ensureMetricsPack(projectId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: metricsPackQueryKey(projectId),
      });
    },
  });
}

export function useUpdateMetricsPack(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (entries: MetricsPackEntry[]) =>
      replaceMetricsPack(projectId, { entries }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: metricsPackQueryKey(projectId),
      });
    },
  });
}
