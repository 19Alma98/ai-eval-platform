"use client";

import { useMutation } from "@tanstack/react-query";
import { postReleaseCheck } from "@/lib/api/release";

export function releaseCheckMutationKey(projectId: string) {
  return ["release-check", projectId] as const;
}

export type ReleaseCheckInput = {
  experiment_id: string;
  baseline_experiment_id?: string | null;
  policy: Record<string, unknown>;
};

export function useReleaseCheck(projectId: string) {
  return useMutation({
    mutationKey: releaseCheckMutationKey(projectId),
    mutationFn: (body: ReleaseCheckInput) => postReleaseCheck(projectId, body),
  });
}
