"use client";

import type { ReactNode } from "react";
import { ApiKeyPrompt } from "@/components/api-key-prompt";
import { useAuth } from "@/lib/auth-context";

/** Shows the app, or the API key prompt when the server requires a key. */
export function ApiKeyGate({ children }: { children: ReactNode }) {
  const { phase } = useAuth();
  if (phase === "checking") return null;
  if (phase === "locked") return <ApiKeyPrompt />;
  return <>{children}</>;
}
