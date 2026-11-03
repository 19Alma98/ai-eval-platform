import type { ApiKey, ApiKeyScope, AuthStatus } from "@/lib/api/types";

export type ScopeOption = { value: ApiKeyScope; label: string; hint: string };

export const SCOPE_OPTIONS: ScopeOption[] = [
  { value: "ingest", label: "Ingest", hint: "Sends traces and scores. Cannot read data." },
  { value: "read", label: "Read", hint: "Opens the dashboard. Cannot change anything." },
  { value: "admin", label: "Admin", hint: "Full access, including API keys." },
];

export const DEFAULT_SCOPE: ApiKeyScope = "ingest";

export function scopeOption(scope: ApiKeyScope): ScopeOption {
  return SCOPE_OPTIONS.find((o) => o.value === scope) ?? SCOPE_OPTIONS[0];
}

/** Active keys first, then newest first. */
export function sortApiKeys(keys: ApiKey[]): ApiKey[] {
  return [...keys].sort((a, b) => {
    if (Boolean(a.revoked_at) !== Boolean(b.revoked_at)) return a.revoked_at ? 1 : -1;
    return b.created_at.localeCompare(a.created_at);
  });
}

export type KeyAccess = "auth-off" | "not-admin" | "admin";

export function keyAccess(status: AuthStatus): KeyAccess {
  if (!status.auth_required) return "auth-off";
  return status.scope === "admin" ? "admin" : "not-admin";
}
