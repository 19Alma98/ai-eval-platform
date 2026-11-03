"use client";

import { EmptyState } from "@/components/empty-state";
import { PageIntro } from "@/components/page-intro";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/lib/auth-context";
import { keyAccess } from "./api-key-format";
import { ApiKeyList } from "./api-key-list";

export function SettingsPage() {
  const { status, signOut } = useAuth();
  const access = keyAccess(status);

  return (
    <>
      <PageIntro
        title="Settings"
        glossary="API keys for apps, CI and people. Each key has a name and a scope."
        actions={
          status.auth_required ? (
            <Button type="button" variant="outline" size="sm" onClick={() => void signOut()}>
              Sign out
            </Button>
          ) : null
        }
      />
      {access === "auth-off" ? (
        <EmptyState
          title="Authentication is off"
          description="Set OPENGRADE_API_KEY on the server to require API keys."
        />
      ) : access === "not-admin" ? (
        <EmptyState
          title="Admin key required"
          description={`Signed in with ${status.key_name ?? "a key"} (${status.scope}).`}
        />
      ) : (
        <ApiKeyList />
      )}
    </>
  );
}
