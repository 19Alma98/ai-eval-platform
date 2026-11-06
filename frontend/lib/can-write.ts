import type { AuthStatus } from "@/lib/api/types";

export function canWrite(status: AuthStatus, phase: "checking" | "open" | "locked"): boolean {
  if (phase !== "open") return false;
  if (!status.auth_required) return true;
  return status.scope === "admin";
}
