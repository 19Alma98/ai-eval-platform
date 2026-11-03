import { apiGet, throwApiError, withBasePath } from "./client";
import type { AuthStatus } from "./types";

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
