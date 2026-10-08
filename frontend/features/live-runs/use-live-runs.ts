"use client";

import { useQuery } from "@tanstack/react-query";
import {
  getLiveInteraction,
  getLiveJudgeCalibration,
  listLiveInteractions,
} from "@/lib/api/live-runs";

export function liveRunsQueryKey(
  projectId: string,
  filters?: { judgeStatus?: string; failedOnly?: boolean; search?: string },
) {
  return [
    "live-runs",
    projectId,
    filters?.judgeStatus ?? "",
    filters?.failedOnly ? "failed" : "",
    filters?.search ?? "",
  ] as const;
}

export function useLiveRuns(
  projectId: string | null,
  filters?: { judgeStatus?: string; failedOnly?: boolean; search?: string },
) {
  const key = projectId ?? "";
  return useQuery({
    queryKey: liveRunsQueryKey(key, filters),
    queryFn: () =>
      listLiveInteractions(key, {
        judgeStatus: filters?.judgeStatus,
        failedOnly: filters?.failedOnly,
        search: filters?.search,
      }),
    enabled: Boolean(projectId),
    refetchInterval: 5000,
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

export function liveRunQueryKey(id: string) {
  return ["live-run", id] as const;
}

export function useLiveRun(id: string | null) {
  const key = id ?? "";
  return useQuery({
    queryKey: liveRunQueryKey(key),
    queryFn: () => getLiveInteraction(key),
    enabled: Boolean(id),
    refetchInterval: (query) => {
      const status = query.state.data?.judge_status;
      return status === "pending" || status === "running" ? 3000 : false;
    },
  });
}
