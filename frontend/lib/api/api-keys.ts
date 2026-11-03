import { apiDelete, apiGet, apiPost } from "./client";
import type { ApiKey, ApiKeyScope, CreatedApiKey } from "./types";

export function listApiKeys(): Promise<ApiKey[]> {
  return apiGet<ApiKey[]>("/api/v1/api-keys");
}

export function createApiKey(body: { name: string; scope: ApiKeyScope }): Promise<CreatedApiKey> {
  return apiPost<CreatedApiKey>("/api/v1/api-keys", body);
}

export function revokeApiKey(id: string): Promise<void> {
  return apiDelete(`/api/v1/api-keys/${encodeURIComponent(id)}`);
}
