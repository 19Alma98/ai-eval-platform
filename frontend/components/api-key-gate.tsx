"use client";

import { useQueryClient } from "@tanstack/react-query";
import { type FormEvent, type ReactNode, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { createSession, getAuthStatus } from "@/lib/api/auth";
import { ApiError, UNAUTHORIZED_EVENT, formatErrorForUi } from "@/lib/api/client";

type GateState = "checking" | "open" | "locked";

/**
 * Asks for the server's API key when OPENGRADE_API_KEY is set. Not a user login: the
 * key is posted once and exchanged for an HttpOnly session cookie. Without a key
 * configured on the server the gate is invisible.
 */
export function ApiKeyGate({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [state, setState] = useState<GateState>("checking");
  const [key, setKey] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getAuthStatus()
      .then((status) => {
        if (!cancelled) setState(status.authenticated ? "open" : "locked");
      })
      // Unreachable API: let the pages show their usual network errors.
      .catch(() => {
        if (!cancelled) setState("open");
      });
    const lock = () => setState("locked");
    window.addEventListener(UNAUTHORIZED_EVENT, lock);
    return () => {
      cancelled = true;
      window.removeEventListener(UNAUTHORIZED_EVENT, lock);
    };
  }, []);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!key.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      await createSession(key.trim());
      setKey("");
      setState("open");
      await queryClient.invalidateQueries();
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 401
          ? "That key is not valid for this server."
          : formatErrorForUi(err),
      );
    } finally {
      setSubmitting(false);
    }
  }

  if (state === "checking") return null;
  if (state === "open") return <>{children}</>;

  return (
    <main className="flex min-h-screen items-center justify-center px-4">
      <form
        onSubmit={onSubmit}
        className="w-full max-w-sm rounded-md border border-border bg-surface p-6"
      >
        <h1 className="text-base font-medium text-foreground">API key required</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          This OpenGrade server is protected. Paste the value of{" "}
          <code className="font-mono text-xs">OPENGRADE_API_KEY</code> to open the dashboard.
        </p>
        <label htmlFor="opengrade-api-key" className="mt-4 block text-sm font-medium">
          API key
        </label>
        <Input
          id="opengrade-api-key"
          type="password"
          autoComplete="off"
          autoFocus
          value={key}
          onChange={(e) => setKey(e.target.value)}
          aria-invalid={error ? true : undefined}
          className="mt-1"
        />
        {error ? (
          <p role="alert" className="mt-2 text-sm text-destructive">
            {error}
          </p>
        ) : null}
        <Button type="submit" className="mt-4 w-full" disabled={submitting || !key.trim()}>
          {submitting ? "Checking…" : "Continue"}
        </Button>
      </form>
    </main>
  );
}
