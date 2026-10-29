"use client";

import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { getLiveInteraction } from "@/lib/api/live-runs";
import { getTrace, listTraces } from "@/lib/api/traces";

export type TraceFilters = {
  status?: string;
  search?: string;
  since?: string;
  environment?: string | null;
  version?: string | null;
};

export function tracesQueryKey(projectId: string, filters: TraceFilters) {
  return [
    "traces",
    projectId,
    filters.status ?? "",
    filters.search ?? "",
    filters.since ?? "",
    filters.environment ?? "",
    filters.version ?? "",
  ] as const;
}

export function useTraces(projectId: string | null, filters: TraceFilters) {
  const key = projectId ?? "";
  return useInfiniteQuery({
    queryKey: tracesQueryKey(key, filters),
    queryFn: ({ pageParam }) =>
      listTraces(key, { ...filters, cursor: pageParam ?? undefined, limit: 50 }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
    enabled: Boolean(projectId),
  });
}

export function traceQueryKey(projectId: string, traceId: string) {
  return ["trace", projectId, traceId] as const;
}

export function useTrace(projectId: string | null, traceId: string | null) {
  return useQuery({
    queryKey: traceQueryKey(projectId ?? "", traceId ?? ""),
    queryFn: () => getTrace(projectId!, traceId!),
    enabled: Boolean(projectId && traceId),
  });
}

/** The live interaction a production trace produced, for its judge claims. */
export function useTraceLiveInteraction(interactionId: string | null | undefined) {
  return useQuery({
    queryKey: ["live-run-for-trace", interactionId ?? ""],
    queryFn: () => getLiveInteraction(interactionId!),
    enabled: Boolean(interactionId),
  });
}
