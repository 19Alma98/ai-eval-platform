"use client";

import { useQuery } from "@tanstack/react-query";
import { getDataset, listDatasets } from "@/lib/api/datasets";

export function datasetsQueryKey(projectId: string) {
  return ["datasets", projectId] as const;
}

export function datasetsQueryOptions(projectId: string) {
  return {
    queryKey: datasetsQueryKey(projectId),
    queryFn: () => listDatasets(projectId),
  } as const;
}

export function useDatasets(projectId: string | null) {
  const key = projectId ?? "";
  return useQuery({
    ...datasetsQueryOptions(key),
    enabled: Boolean(projectId),
  });
}

export function datasetQueryKey(datasetId: string) {
  return ["dataset", datasetId] as const;
}

export function datasetQueryOptions(datasetId: string) {
  return {
    queryKey: datasetQueryKey(datasetId),
    queryFn: () => getDataset(datasetId),
  } as const;
}

export function useDataset(datasetId: string | null) {
  const key = datasetId ?? "";
  return useQuery({
    ...datasetQueryOptions(key),
    enabled: Boolean(datasetId),
  });
}
