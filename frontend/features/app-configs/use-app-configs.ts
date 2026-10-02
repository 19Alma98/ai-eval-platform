"use client";

import { useQuery } from "@tanstack/react-query";
import {
  listAliases,
  listAppConfigVersions,
  listAppConfigs,
} from "@/lib/api/app-configs";

export function appConfigsQueryKey(projectId: string) {
  return ["app-configs", projectId] as const;
}

export function appConfigsQueryOptions(projectId: string) {
  return {
    queryKey: appConfigsQueryKey(projectId),
    queryFn: () => listAppConfigs(projectId, { latest: true }),
  } as const;
}

export function useAppConfigs(projectId: string | null) {
  const key = projectId ?? "";
  return useQuery({
    ...appConfigsQueryOptions(key),
    enabled: Boolean(projectId),
  });
}

export function appConfigAliasesQueryKey(projectId: string) {
  return ["app-config-aliases", projectId] as const;
}

export function appConfigAliasesQueryOptions(projectId: string) {
  return {
    queryKey: appConfigAliasesQueryKey(projectId),
    queryFn: () => listAliases(projectId),
  } as const;
}

export function useAppConfigAliases(projectId: string | null) {
  const key = projectId ?? "";
  return useQuery({
    ...appConfigAliasesQueryOptions(key),
    enabled: Boolean(projectId),
  });
}

export function appConfigVersionsQueryKey(projectId: string, name: string) {
  return ["app-config-versions", projectId, name] as const;
}

export function appConfigVersionsQueryOptions(
  projectId: string,
  name: string,
) {
  return {
    queryKey: appConfigVersionsQueryKey(projectId, name),
    queryFn: () => listAppConfigVersions(projectId, name),
  } as const;
}

export function useAppConfigVersions(
  projectId: string | null,
  name: string | null,
) {
  const pid = projectId ?? "";
  const family = name ?? "";
  return useQuery({
    ...appConfigVersionsQueryOptions(pid, family),
    enabled: Boolean(projectId && name),
  });
}
