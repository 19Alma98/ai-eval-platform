"use client";

import { useState, type SubmitEvent } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError, formatErrorForUi } from "@/lib/api/client";
import { useAuth } from "@/lib/auth-context";

export function ApiKeyPrompt() {
  const { unlock } = useAuth();
  const [key, setKey] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function handleSubmit(e: SubmitEvent) {
    e.preventDefault();
    const value = key.trim();
    if (!value) return;
    setPending(true);
    setError(null);
    try {
      await unlock(value);
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 401 ? "Invalid API key." : formatErrorForUi(err),
      );
      setPending(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center px-4">
      <form
        onSubmit={handleSubmit}
        className="flex w-full max-w-sm flex-col gap-3 rounded-md border border-border bg-surface p-5"
      >
        <div>
          <h1 className="text-sm font-semibold text-foreground">OpenGrade</h1>
          <p className="mt-1 text-sm text-muted-foreground">Enter a read or admin API key.</p>
        </div>
        <div className="flex flex-col gap-1.5">
          <label htmlFor="api-key-prompt" className="text-sm font-medium">
            API key
          </label>
          <Input
            id="api-key-prompt"
            type="password"
            autoComplete="off"
            autoFocus
            value={key}
            onChange={(e) => setKey(e.target.value)}
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? "api-key-prompt-error" : undefined}
          />
          {error ? (
            <p id="api-key-prompt-error" className="text-sm text-destructive">
              {error}
            </p>
          ) : null}
        </div>
        <Button type="submit" disabled={pending || !key.trim()}>
          {pending ? "Checking…" : "Continue"}
        </Button>
      </form>
    </main>
  );
}
