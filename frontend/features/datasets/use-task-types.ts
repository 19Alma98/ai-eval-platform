"use client";

import { useQuery } from "@tanstack/react-query";
import { listTaskTypes } from "@/lib/api/datasets";

export const taskTypesQueryKey = ["task-types"] as const;

export function taskTypesQueryOptions() {
  return {
    queryKey: taskTypesQueryKey,
    queryFn: () => listTaskTypes(),
    staleTime: 60_000,
  };
}

export function useTaskTypes() {
  return useQuery(taskTypesQueryOptions());
}

export function taskTypeLabel(
  taskTypes: { id: string; label: string }[] | undefined,
  taskType: string | null | undefined,
): string | null {
  if (!taskType) return null;
  return taskTypes?.find((t) => t.id === taskType)?.label ?? taskType;
}
