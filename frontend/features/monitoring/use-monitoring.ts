"use client";

import { useQuery } from "@tanstack/react-query";
import { keepPreviousInProject } from "@/lib/queries/keep-previous";
import { getMonitoring, getReleaseFacets, getVersionSummaries } from "@/lib/api/monitoring";
import type { ReleaseFilter } from "@/lib/api/types";

export function monitoringQueryKey(
  projectId: string,
  since: string,
  until: string,
  filter?: ReleaseFilter,
) {
  return [
    "monitoring",
    projectId,
    since,
    until,
    filter?.environment ?? "",
    filter?.version ?? "",
  ] as const;
}

export function useMonitoring(
  projectId: string | null,
  since: string,
  until: string,
  filter?: ReleaseFilter,
) {
  return useQuery({
    queryKey: monitoringQueryKey(projectId ?? "", since, until, filter),
    queryFn: () => getMonitoring(projectId!, since, until, filter),
    enabled: Boolean(projectId),
    // A refresh moves the time window; keep the old numbers until the new ones arrive.
    placeholderData: keepPreviousInProject(projectId ?? ""),
  });
}

export function useReleaseFacets(projectId: string | null, since: string, until?: string) {
  return useQuery({
    queryKey: ["release-facets", projectId ?? "", since, until ?? ""] as const,
    queryFn: () => getReleaseFacets(projectId!, since, until),
    enabled: Boolean(projectId),
    placeholderData: keepPreviousInProject(projectId ?? ""),
  });
}

export function useVersionSummaries(
  projectId: string | null,
  since: string,
  until: string,
  environment: string | null,
  enabled: boolean,
) {
  return useQuery({
    queryKey: ["monitoring-versions", projectId ?? "", since, until, environment ?? ""] as const,
    queryFn: () => getVersionSummaries(projectId!, since, until, environment),
    enabled: Boolean(projectId) && enabled,
  });
}
