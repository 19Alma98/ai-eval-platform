"use client";

import { Plus } from "lucide-react";
import { useState } from "react";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { LoadingBlock } from "@/components/loading-block";
import { RelativeTime } from "@/components/relative-time";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { formatErrorForUi } from "@/lib/api/client";
import type { ApiKey, CreatedApiKey } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { sortApiKeys } from "./api-key-format";
import { ApiKeySecretDialog } from "./api-key-secret-dialog";
import { CreateApiKeyDialog } from "./create-api-key-dialog";
import { RevokeApiKeyDialog } from "./revoke-api-key-dialog";
import { useApiKeys } from "./use-api-keys";

export function ApiKeyList() {
  const query = useApiKeys(true);
  const [createOpen, setCreateOpen] = useState(false);
  const [created, setCreated] = useState<CreatedApiKey | null>(null);
  const [revoking, setRevoking] = useState<ApiKey | null>(null);

  if (query.isLoading) return <LoadingBlock className="min-h-[160px]" />;
  if (query.isError) {
    return (
      <ErrorState
        title="Could not load API keys"
        message={formatErrorForUi(query.error)}
        onRetry={() => void query.refetch()}
      />
    );
  }

  const keys = sortApiKeys(query.data ?? []);
  const newKeyButton = (
    <Button type="button" size="sm" onClick={() => setCreateOpen(true)}>
      <Plus className="size-4" />
      New key
    </Button>
  );

  return (
    <section>
      <div className="mb-3 flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold tracking-tight text-foreground">API keys</h2>
        {keys.length > 0 ? newKeyButton : null}
      </div>

      {keys.length === 0 ? (
        <EmptyState
          title="No API keys"
          description="Only OPENGRADE_API_KEY is accepted."
          action={newKeyButton}
        />
      ) : (
        <ul className="divide-y divide-border rounded-md border border-border bg-surface">
          {keys.map((k) => (
            <li key={k.id} className={cn("flex items-center gap-3 px-3 py-2", k.revoked_at && "opacity-60")}>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="truncate text-sm font-medium text-foreground">{k.name}</span>
                  <Badge variant="outline">{k.scope}</Badge>
                  {k.revoked_at ? <Badge variant="destructive">revoked</Badge> : null}
                </div>
                <div className="mt-0.5 flex flex-wrap gap-x-3 text-xs text-muted-foreground">
                  <code className="font-mono">{k.prefix}…</code>
                  <span>
                    Created <RelativeTime date={k.created_at} />
                  </span>
                  <span>
                    {k.last_used_at ? (
                      <>
                        Used <RelativeTime date={k.last_used_at} />
                      </>
                    ) : (
                      "Never used"
                    )}
                  </span>
                </div>
              </div>
              {!k.revoked_at ? (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="shrink-0 text-muted-foreground hover:text-status-fail"
                  aria-label={`Revoke ${k.name}`}
                  onClick={() => setRevoking(k)}
                >
                  Revoke
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
      )}

      <CreateApiKeyDialog open={createOpen} onOpenChange={setCreateOpen} onCreated={setCreated} />
      <ApiKeySecretDialog created={created} onClose={() => setCreated(null)} />
      <RevokeApiKeyDialog apiKey={revoking} onClose={() => setRevoking(null)} />
    </section>
  );
}
