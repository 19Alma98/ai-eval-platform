"use client";

import { useQuery } from "@tanstack/react-query";
import { getTraceScoreSummary } from "@/lib/api/trace-scores";

export function traceScoreSummaryQueryKey(projectId: string, since: string, until?: string) {
  return ["trace-score-summary", projectId, since, until ?? null] as const;
}

export function useTraceScoreSummary(
  projectId: string | null | undefined,
  since: string,
  until?: string,
) {
  return useQuery({
    queryKey: traceScoreSummaryQueryKey(projectId ?? "", since, until),
    queryFn: () => getTraceScoreSummary(projectId!, since, until),
    enabled: Boolean(projectId),
  });
}
