"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type SubmitEvent } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { createApiKey } from "@/lib/api/api-keys";
import { formatErrorForUi } from "@/lib/api/client";
import type { ApiKeyScope, CreatedApiKey } from "@/lib/api/types";
import { DEFAULT_SCOPE, SCOPE_OPTIONS, scopeOption } from "./api-key-format";
import { apiKeysQueryKey } from "./use-api-keys";

/** Inline form above the key list; no modal. */
export function CreateApiKeyForm({
  onCreated,
  onCancel,
}: {
  onCreated: (key: CreatedApiKey) => void;
  onCancel: () => void;
}) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [scope, setScope] = useState<ApiKeyScope>(DEFAULT_SCOPE);

  const create = useMutation({
    mutationFn: () => createApiKey({ name: name.trim(), scope }),
    onSuccess: async (created) => {
      await queryClient.invalidateQueries({ queryKey: apiKeysQueryKey });
      onCreated(created);
    },
    onError: (err) => toast.error(formatErrorForUi(err)),
  });

  function handleSubmit(e: SubmitEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    create.mutate();
  }

  return (
    <form
      onSubmit={handleSubmit}
      aria-label="New API key"
      className="grid grid-cols-1 gap-x-3 gap-y-2 border-t border-border py-4 sm:grid-cols-[1fr_11rem_auto] sm:items-end"
    >
      <div className="flex flex-col gap-1.5">
        <label htmlFor="api-key-name" className="text-sm font-medium">
          Name
        </label>
        <Input
          id="api-key-name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="prod-chatbot"
          maxLength={200}
          autoFocus
          required
        />
      </div>
      <div className="flex flex-col gap-1.5">
        <label htmlFor="api-key-scope" className="text-sm font-medium">
          Scope
        </label>
        <Select value={scope} onValueChange={(v) => v && setScope(v as ApiKeyScope)}>
          <SelectTrigger id="api-key-scope" className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {SCOPE_OPTIONS.map((o) => (
              <SelectItem key={o.value} value={o.value}>
                {o.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      {/* Mobile: hint under the scope, then the buttons. Desktop: buttons on the field row. */}
      <p className="text-xs text-muted-foreground sm:order-last sm:col-span-3">
        {scopeOption(scope).hint}
      </p>
      <div className="flex gap-2">
        <Button type="button" variant="ghost" onClick={onCancel} disabled={create.isPending}>
          Cancel
        </Button>
        <Button type="submit" disabled={!name.trim() || create.isPending}>
          {create.isPending ? "Creating…" : "Create"}
        </Button>
      </div>
    </form>
  );
}
