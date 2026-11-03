import { apiDelete, apiGet, apiPost, throwApiError, withBasePath } from "./client";

export type ApiKeyScope = "admin" | "read" | "ingest";

export type AuthStatus = {
  auth_required: boolean;
  authenticated: boolean;
  /** Scope of the key behind this browser session; "admin" when auth is off. */
  scope: ApiKeyScope | null;
  key_name: string | null;
};

export type ApiKey = {
  id: string;
  name: string;
  scope: ApiKeyScope;
  /** First characters of the key, to tell keys apart. */
  prefix: string;
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
};

export type CreatedApiKey = ApiKey & {
  /** The key itself: returned once, never stored by the server. */
  key: string;
};

export function getAuthStatus(): Promise<AuthStatus> {
  return apiGet<AuthStatus>("/api/v1/auth/status");
}

/** Exchange an API key for an HttpOnly session cookie; the key is not kept in the browser. */
export async function createSession(apiKey: string): Promise<void> {
  const res = await fetch(withBasePath("/api/v1/auth/session"), {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify({ api_key: apiKey }),
  });
  if (!res.ok) await throwApiError(res);
}

export async function deleteSession(): Promise<void> {
  const res = await fetch(withBasePath("/api/v1/auth/session"), { method: "DELETE" });
  if (!res.ok) await throwApiError(res);
}

export function listApiKeys(): Promise<ApiKey[]> {
  return apiGet<ApiKey[]>("/api/v1/api-keys");
}

export function createApiKey(body: { name: string; scope: ApiKeyScope }): Promise<CreatedApiKey> {
  return apiPost<CreatedApiKey>("/api/v1/api-keys", body);
}

export function revokeApiKey(id: string): Promise<void> {
  return apiDelete(`/api/v1/api-keys/${encodeURIComponent(id)}`);
}
