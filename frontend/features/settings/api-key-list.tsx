"use client";

import { Plus } from "lucide-react";
import { useState } from "react";
import { ErrorState } from "@/components/error-state";
import { LoadingBlock } from "@/components/loading-block";
import { Button } from "@/components/ui/button";
import { formatErrorForUi } from "@/lib/api/client";
import type { CreatedApiKey } from "@/lib/api/types";
import { sortApiKeys } from "./api-key-format";
import { ApiKeyRow } from "./api-key-row";
import { CreateApiKeyForm } from "./create-api-key-form";
import { NewApiKeyNotice } from "./new-api-key-notice";
import { useApiKeys } from "./use-api-keys";

export function ApiKeyList() {
  const query = useApiKeys(true);
  const [creating, setCreating] = useState(false);
  const [created, setCreated] = useState<CreatedApiKey | null>(null);

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

  return (
    <section className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold tracking-tight text-foreground">API keys</h2>
        {!creating ? (
          <Button
            type="button"
            size="sm"
            onClick={() => {
              setCreated(null);
              setCreating(true);
            }}
          >
            <Plus className="size-4" />
            New key
          </Button>
        ) : null}
      </div>

      {/* Form, new key and list share one ruled block: one line between each. */}
      <div className="border-b border-border">
        {creating ? (
          <CreateApiKeyForm
            onCancel={() => setCreating(false)}
            onCreated={(key) => {
              setCreating(false);
              setCreated(key);
            }}
          />
        ) : null}
        {created ? <NewApiKeyNotice created={created} onDismiss={() => setCreated(null)} /> : null}
        {keys.length === 0 ? (
          <p className="border-t border-border py-3 text-sm text-muted-foreground">
            No API keys. Only OPENGRADE_API_KEY is accepted.
          </p>
        ) : (
          <ul className="divide-y divide-border border-t border-border">
            {keys.map((k) => (
              <ApiKeyRow key={k.id} apiKey={k} />
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
