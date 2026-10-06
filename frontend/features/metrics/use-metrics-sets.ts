"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ensureMetricsPack } from "@/lib/api/metrics-packs";
import {
  createMetricsSet,
  deleteMetricsSetEntry,
  getMetricsSet,
  listMetricsSets,
  patchMetricsSet,
  versionMetricsSet,
} from "@/lib/api/metrics-sets";
import type {
  CreateMetricsSetBody,
  MetricsSetEntryInput,
  PatchMetricsSetBody,
} from "@/lib/api/types";

export function metricsSetsQueryKey(projectId: string) {
  return ["metrics-sets", projectId] as const;
}

export function metricsSetsQueryOptions(projectId: string) {
  return {
    queryKey: metricsSetsQueryKey(projectId),
    queryFn: () => listMetricsSets(projectId),
  } as const;
}

export function useMetricsSets(projectId: string | null) {
  return useQuery({
    ...metricsSetsQueryOptions(projectId ?? ""),
    enabled: Boolean(projectId),
  });
}

export function metricsSetQueryKey(metricsSetId: string) {
  return ["metrics-set", metricsSetId] as const;
}

export function metricsSetQueryOptions(metricsSetId: string) {
  return {
    queryKey: metricsSetQueryKey(metricsSetId),
    queryFn: () => getMetricsSet(metricsSetId),
  } as const;
}

export function useMetricsSet(metricsSetId: string | null) {
  return useQuery({
    ...metricsSetQueryOptions(metricsSetId ?? ""),
    enabled: Boolean(metricsSetId),
  });
}

export function useEnsureMetricsPackForProject(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => ensureMetricsPack(projectId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: metricsSetsQueryKey(projectId),
      });
    },
  });
}

export function useCreateMetricsSet(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: CreateMetricsSetBody) =>
      createMetricsSet(projectId, body),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: metricsSetsQueryKey(projectId),
      });
    },
  });
}

export function usePatchMetricsSet(metricsSetId: string, projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: PatchMetricsSetBody) =>
      patchMetricsSet(metricsSetId, body),
    onSuccess: async (data) => {
      queryClient.setQueryData(metricsSetQueryKey(metricsSetId), data);
      await queryClient.invalidateQueries({
        queryKey: metricsSetsQueryKey(projectId),
      });
    },
  });
}

export function useVersionMetricsSet(
  metricsSetId: string,
  projectId: string,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => versionMetricsSet(metricsSetId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: metricsSetsQueryKey(projectId),
      });
    },
  });
}

export function useDeleteMetricsSetEntry(
  metricsSetId: string,
  projectId: string,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (entryId: string) =>
      deleteMetricsSetEntry(metricsSetId, entryId),
    onSuccess: async (data) => {
      queryClient.setQueryData(metricsSetQueryKey(metricsSetId), data);
      await queryClient.invalidateQueries({
        queryKey: metricsSetsQueryKey(projectId),
      });
    },
  });
}

export type { MetricsSetEntryInput };
