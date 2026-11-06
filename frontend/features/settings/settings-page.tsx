"use client";

import { EmptyState } from "@/components/empty-state";
import { PageIntro } from "@/components/page-intro";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/lib/auth-context";
import { keyAccess } from "./api-key-format";
import { ApiKeyList } from "./api-key-list";
import { LlmSettingsForm } from "./llm-settings-form";

export function SettingsPage() {
  const { status, signOut } = useAuth();
  const access = keyAccess(status);
  const canEditLlm = access === "admin" || access === "auth-off";
  const canManageKeys = access === "admin";

  return (
    <>
      <PageIntro
        title="Settings"
        glossary="API keys for apps, CI and people, and LLM judge configuration."
        actions={
          status.auth_required ? (
            <Button type="button" variant="outline" size="sm" onClick={() => void signOut()}>
              Sign out
            </Button>
          ) : null
        }
      />
      {access === "not-admin" ? (
        <EmptyState
          title="Admin key required"
          description={`Signed in with ${status.key_name ?? "a key"} (${status.scope}).`}
        />
      ) : (
        <div className="flex flex-col gap-10">
          {canManageKeys ? (
            <ApiKeyList />
          ) : (
            <EmptyState
              title="Authentication is off"
              description="Set OPENGRADE_API_KEY on the server to require API keys."
            />
          )}
          {canEditLlm ? <LlmSettingsForm /> : null}
        </div>
      )}
    </>
  );
}
