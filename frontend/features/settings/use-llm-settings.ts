"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { formatErrorForUi } from "@/lib/api/client";
import { getLlmSettings, resetLlmSettings, updateLlmSettings } from "@/lib/api/llm-settings";
import type { LlmSettingsUpdate } from "@/lib/api/types";

export const llmSettingsQueryKey = ["llm-settings"] as const;

export function useLlmSettings(enabled: boolean) {
  return useQuery({ queryKey: llmSettingsQueryKey, queryFn: getLlmSettings, enabled });
}

export function useUpdateLlmSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: LlmSettingsUpdate) => updateLlmSettings(body),
    onSuccess: async (data) => {
      queryClient.setQueryData(llmSettingsQueryKey, data);
      toast.success("LLM settings saved");
    },
    onError: (err) => toast.error(formatErrorForUi(err)),
  });
}

export function useResetLlmSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => resetLlmSettings(),
    onSuccess: async (data) => {
      queryClient.setQueryData(llmSettingsQueryKey, data);
      toast.success("LLM overlays reset to environment");
    },
    onError: (err) => toast.error(formatErrorForUi(err)),
  });
}
