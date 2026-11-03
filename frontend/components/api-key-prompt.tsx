"use client";

import { useState, type SubmitEvent } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError, formatErrorForUi } from "@/lib/api/client";
import { useAuth } from "@/lib/auth-context";

/** Full page, no card: the app's name, one field, one button. */
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
    <main className="mx-auto flex min-h-screen w-full max-w-md flex-col justify-center px-4">
      <h1 className="font-serif text-2xl text-foreground">OpenGrade</h1>
      <form
        onSubmit={handleSubmit}
        className="mt-6 flex flex-col gap-1.5 border-t border-border pt-6"
      >
        <label htmlFor="api-key-prompt" className="text-sm font-medium">
          API key
        </label>
        <div className="flex gap-2">
          <Input
            id="api-key-prompt"
            type="password"
            autoComplete="off"
            autoFocus
            value={key}
            onChange={(e) => setKey(e.target.value)}
            aria-invalid={error ? true : undefined}
            aria-describedby="api-key-prompt-help"
          />
          <Button type="submit" disabled={pending || !key.trim()}>
            {pending ? "Checking…" : "Continue"}
          </Button>
        </div>
        <p
          id="api-key-prompt-help"
          className={error ? "text-sm text-destructive" : "text-xs text-muted-foreground"}
        >
          {error ?? "A read or admin key for this server."}
        </p>
      </form>
    </main>
  );
}
