"use client";

import { useQuery } from "@tanstack/react-query";
import {
  compareExperimentItems,
  compareExperiments,
  getExperiment,
  listExperiments,
  summarizeExperiment,
} from "@/lib/api/experiments";
import { listEvaluators } from "@/lib/api/evaluators";

export function experimentsQueryKey(projectId: string) {
  return ["experiments", projectId] as const;
}

export function experimentsQueryOptions(projectId: string) {
  return {
    queryKey: experimentsQueryKey(projectId),
    queryFn: () => listExperiments(projectId),
  } as const;
}

export function useExperiments(projectId: string | null) {
  const key = projectId ?? "";
  return useQuery({
    ...experimentsQueryOptions(key),
    enabled: Boolean(projectId),
  });
}

export function experimentQueryKey(experimentId: string) {
  return ["experiment", experimentId] as const;
}

export function experimentQueryOptions(experimentId: string) {
  return {
    queryKey: experimentQueryKey(experimentId),
    queryFn: () => getExperiment(experimentId),
  } as const;
}

export function useExperiment(experimentId: string | null) {
  const key = experimentId ?? "";
  return useQuery({
    ...experimentQueryOptions(key),
    enabled: Boolean(experimentId),
  });
}

export function experimentSummaryQueryKey(experimentId: string) {
  return ["experiment-summary", experimentId] as const;
}

export function experimentSummaryQueryOptions(experimentId: string) {
  return {
    queryKey: experimentSummaryQueryKey(experimentId),
    queryFn: () => summarizeExperiment(experimentId),
  } as const;
}

export function useExperimentSummary(experimentId: string | null) {
  const key = experimentId ?? "";
  return useQuery({
    ...experimentSummaryQueryOptions(key),
    enabled: Boolean(experimentId),
  });
}

export function experimentCompareQueryKey(
  experimentId: string,
  baselineId: string,
) {
  return ["experiment-compare", experimentId, baselineId] as const;
}

export function experimentCompareQueryOptions(
  experimentId: string,
  baselineId: string,
) {
  return {
    queryKey: experimentCompareQueryKey(experimentId, baselineId),
    queryFn: () => compareExperiments(experimentId, baselineId),
  } as const;
}

export function useExperimentCompare(
  experimentId: string | null,
  baselineId: string | null,
) {
  const expKey = experimentId ?? "";
  const baseKey = baselineId ?? "";
  return useQuery({
    ...experimentCompareQueryOptions(expKey, baseKey),
    enabled: Boolean(experimentId && baselineId),
  });
}

export type ExperimentCompareItemsOpts = {
  evaluatorId?: string;
  regressionsOnly?: boolean;
};

export function experimentCompareItemsQueryKey(
  experimentId: string,
  baselineId: string,
  opts?: ExperimentCompareItemsOpts,
) {
  return [
    "experiment-compare-items",
    experimentId,
    baselineId,
    opts?.evaluatorId ?? null,
    opts?.regressionsOnly ?? false,
  ] as const;
}

export function experimentCompareItemsQueryOptions(
  experimentId: string,
  baselineId: string,
  opts?: ExperimentCompareItemsOpts,
) {
  return {
    queryKey: experimentCompareItemsQueryKey(experimentId, baselineId, opts),
    queryFn: () => compareExperimentItems(experimentId, baselineId, opts),
  } as const;
}

export function useExperimentCompareItems(
  experimentId: string | null,
  baselineId: string | null,
  opts?: ExperimentCompareItemsOpts,
) {
  const expKey = experimentId ?? "";
  const baseKey = baselineId ?? "";
  return useQuery({
    ...experimentCompareItemsQueryOptions(expKey, baseKey, opts),
    enabled: Boolean(experimentId && baselineId),
  });
}

export function evaluatorsQueryKey(projectId: string) {
  return ["evaluators", projectId] as const;
}

export function evaluatorsQueryOptions(projectId: string) {
  return {
    queryKey: evaluatorsQueryKey(projectId),
    queryFn: () => listEvaluators(projectId),
  } as const;
}

export function useEvaluators(projectId: string | null) {
  const key = projectId ?? "";
  return useQuery({
    ...evaluatorsQueryOptions(key),
    enabled: Boolean(projectId),
  });
}
