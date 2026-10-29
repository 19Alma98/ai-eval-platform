"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { formatErrorForUi } from "@/lib/api/client";
import {
  deleteExperimentAlias,
  listExperimentAliasHistory,
  listExperimentAliases,
  setExperimentAlias,
  type SetExperimentAliasBody,
} from "@/lib/api/experiment-aliases";

export function experimentAliasesQueryKey(projectId: string) {
  return ["experiment-aliases", projectId] as const;
}

export function experimentAliasesQueryOptions(projectId: string) {
  return {
    queryKey: experimentAliasesQueryKey(projectId),
    queryFn: () => listExperimentAliases(projectId),
  } as const;
}

export function useExperimentAliases(projectId: string | null) {
  const key = projectId ?? "";
  return useQuery({
    ...experimentAliasesQueryOptions(key),
    enabled: Boolean(projectId),
  });
}

export function experimentAliasHistoryQueryKey(
  projectId: string,
  alias: string,
) {
  return ["experiment-alias-history", projectId, alias] as const;
}

export function experimentAliasHistoryQueryOptions(
  projectId: string,
  alias: string,
) {
  return {
    queryKey: experimentAliasHistoryQueryKey(projectId, alias),
    queryFn: () => listExperimentAliasHistory(projectId, alias),
  } as const;
}

export function useExperimentAliasHistory(
  projectId: string | null,
  alias: string | null,
) {
  const pid = projectId ?? "";
  const name = alias ?? "";
  return useQuery({
    ...experimentAliasHistoryQueryOptions(pid, name),
    enabled: Boolean(projectId && alias),
  });
}

async function invalidateAliasQueries(
  queryClient: ReturnType<typeof useQueryClient>,
  projectId: string,
  alias?: string,
) {
  await queryClient.invalidateQueries({
    queryKey: experimentAliasesQueryKey(projectId),
  });
  if (alias) {
    await queryClient.invalidateQueries({
      queryKey: experimentAliasHistoryQueryKey(projectId, alias),
    });
  } else {
    await queryClient.invalidateQueries({
      queryKey: ["experiment-alias-history", projectId],
    });
  }
}

export function useSetExperimentAlias(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      alias,
      ...body
    }: SetExperimentAliasBody & { alias: string }) =>
      setExperimentAlias(projectId, alias, body),
    onSuccess: async (result, vars) => {
      await invalidateAliasQueries(queryClient, projectId, vars.alias);
      if (result.changed === false) {
        toast.message(`Alias “${vars.alias}” already points here`);
      } else {
        toast.success(`Alias “${vars.alias}” updated`);
      }
    },
    onError: (err) => {
      toast.error(formatErrorForUi(err));
    },
  });
}

export function useDeleteExperimentAlias(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (alias: string) => deleteExperimentAlias(projectId, alias),
    onSuccess: async (_void, alias) => {
      await invalidateAliasQueries(queryClient, projectId, alias);
      toast.success(`Alias “${alias}” removed`);
    },
    onError: (err) => {
      toast.error(formatErrorForUi(err));
    },
  });
}
