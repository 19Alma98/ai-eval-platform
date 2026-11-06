"use client";

import { useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { createSession, deleteSession, getAuthStatus } from "@/lib/api/auth";
import { UNAUTHORIZED_EVENT } from "@/lib/api/client";
import type { AuthStatus } from "@/lib/api/types";
import { canWrite } from "@/lib/can-write";

/** `checking` until the first status call; `locked` when the server wants a key. */
export type AuthPhase = "checking" | "open" | "locked";

type AuthContextValue = {
  phase: AuthPhase;
  status: AuthStatus;
  /** Exchange a key for a session cookie. Throws ApiError on a wrong or ingest key. */
  unlock: (apiKey: string) => Promise<void>;
  signOut: () => Promise<void>;
};

const OPEN_STATUS: AuthStatus = {
  auth_required: false,
  authenticated: true,
  scope: "admin",
  key_name: null,
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [phase, setPhase] = useState<AuthPhase>("checking");
  const [status, setStatus] = useState<AuthStatus>(OPEN_STATUS);

  const apply = useCallback((next: AuthStatus) => {
    setStatus(next);
    setPhase(next.authenticated ? "open" : "locked");
  }, []);

  useEffect(() => {
    let cancelled = false;
    getAuthStatus()
      .then((next) => {
        if (!cancelled) apply(next);
      })
      // Unreachable API: let the pages show their usual network errors.
      .catch(() => {
        if (!cancelled) setPhase("open");
      });
    // Any 401 (key revoked or rotated, session expired) asks for a key again.
    const lock = () => setPhase("locked");
    window.addEventListener(UNAUTHORIZED_EVENT, lock);
    return () => {
      cancelled = true;
      window.removeEventListener(UNAUTHORIZED_EVENT, lock);
    };
  }, [apply]);

  const unlock = useCallback(
    async (apiKey: string) => {
      await createSession(apiKey);
      apply(await getAuthStatus());
      await queryClient.invalidateQueries();
    },
    [apply, queryClient],
  );

  const signOut = useCallback(async () => {
    await deleteSession();
    queryClient.clear();
    setPhase("locked");
  }, [queryClient]);

  const value = useMemo(
    () => ({ phase, status, unlock, signOut }),
    [phase, status, unlock, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}

export function useCanWrite(): boolean {
  const { phase, status } = useAuth();
  return canWrite(status, phase);
}
