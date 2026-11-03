"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type SubmitEvent } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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

export function CreateApiKeyDialog({
  open,
  onOpenChange,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (key: CreatedApiKey) => void;
}) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [scope, setScope] = useState<ApiKeyScope>(DEFAULT_SCOPE);

  const create = useMutation({
    mutationFn: () => createApiKey({ name: name.trim(), scope }),
    onSuccess: async (created) => {
      await queryClient.invalidateQueries({ queryKey: apiKeysQueryKey });
      setName("");
      setScope(DEFAULT_SCOPE);
      onOpenChange(false);
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
    <Dialog open={open} onOpenChange={(next) => !create.isPending && onOpenChange(next)}>
      <DialogContent className="sm:max-w-md">
        <form onSubmit={handleSubmit}>
          <DialogHeader>
            <DialogTitle>New API key</DialogTitle>
          </DialogHeader>
          <div className="flex flex-col gap-3 py-4">
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
              <p className="text-xs text-muted-foreground">{scopeOption(scope).hint}</p>
            </div>
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={!name.trim() || create.isPending}>
              {create.isPending ? "Creating…" : "Create"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
