"use client";

import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { ApiError } from "@/lib/api/client";
import { keepPreviousInProject } from "@/lib/queries/keep-previous";
import {
  getLiveInteraction,
  getLiveJudgeCalibration,
  listLiveInteractions,
} from "@/lib/api/live-runs";

export type LiveRunFilters = {
  judgeStatus?: string;
  failedOnly?: boolean;
  search?: string;
  since?: string;
  until?: string;
  metadata?: string[];
};

export function liveRunsQueryKey(projectId: string, filters?: LiveRunFilters) {
  return [
    "live-runs",
    projectId,
    filters?.judgeStatus ?? "",
    filters?.failedOnly ? "failed" : "",
    filters?.search ?? "",
    filters?.since ?? "",
    filters?.until ?? "",
    (filters?.metadata ?? []).join("\u0000"),
  ] as const;
}

export function useLiveRuns(projectId: string | null, filters?: LiveRunFilters) {
  const key = projectId ?? "";
  return useInfiniteQuery({
    queryKey: liveRunsQueryKey(key, filters),
    queryFn: ({ pageParam }) =>
      listLiveInteractions(key, {
        judgeStatus: filters?.judgeStatus,
        failedOnly: filters?.failedOnly,
        search: filters?.search,
        since: filters?.since,
        until: filters?.until,
        metadata: filters?.metadata,
        offset: pageParam ?? 0,
        limit: 50,
      }),
    initialPageParam: 0 as number,
    getNextPageParam: (last) =>
      last.next_offset != null ? last.next_offset : undefined,
    enabled: Boolean(projectId),
    refetchInterval: 5000,
    placeholderData: keepPreviousInProject(key),
  });
}

export function liveCalibrationQueryKey(projectId: string) {
  return ["live-calibration", projectId] as const;
}

export function useLiveJudgeCalibration(projectId: string | null) {
  const key = projectId ?? "";
  return useQuery({
    queryKey: liveCalibrationQueryKey(key),
    queryFn: () => getLiveJudgeCalibration(key),
    enabled: Boolean(projectId),
  });
}

export function liveRunQueryKey(id: string, projectId: string) {
  return ["live-run", projectId, id] as const;
}

export function useLiveRun(id: string | null, projectId: string | null) {
  const key = id ?? "";
  const projectKey = projectId ?? "";
  return useQuery({
    queryKey: liveRunQueryKey(key, projectKey),
    queryFn: async () => {
      const row = await getLiveInteraction(key);
      if (row.project_id !== projectKey) {
        throw new ApiError(404, "Live interaction not found in this project.");
      }
      return row;
    },
    enabled: Boolean(id && projectId),
    refetchInterval: (query) => {
      const status = query.state.data?.judge_status;
      return status === "pending" || status === "running" ? 3000 : false;
    },
  });
}
