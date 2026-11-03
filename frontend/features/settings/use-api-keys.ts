"use client";

import { useQuery } from "@tanstack/react-query";
import { listApiKeys } from "@/lib/api/api-keys";

export const apiKeysQueryKey = ["api-keys"] as const;

export function useApiKeys(enabled: boolean) {
  return useQuery({ queryKey: apiKeysQueryKey, queryFn: listApiKeys, enabled });
}
