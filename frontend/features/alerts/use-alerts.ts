"use client";

import { useQuery } from "@tanstack/react-query";
import { listAlertEvents, listAlertRules } from "@/lib/api/alerts";

export function alertRulesQueryKey(projectId: string) {
  return ["alert-rules", projectId] as const;
}

export function alertEventsQueryKey(projectId: string) {
  return ["alert-events", projectId] as const;
}

export function useAlertRules(projectId: string | null) {
  return useQuery({
    queryKey: alertRulesQueryKey(projectId ?? ""),
    queryFn: () => listAlertRules(projectId!),
    enabled: Boolean(projectId),
  });
}

export function useAlertEvents(projectId: string | null) {
  return useQuery({
    queryKey: alertEventsQueryKey(projectId ?? ""),
    queryFn: () => listAlertEvents(projectId!),
    enabled: Boolean(projectId),
  });
}
