"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { RelativeTime } from "@/components/relative-time";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { revokeApiKey } from "@/lib/api/api-keys";
import { formatErrorForUi } from "@/lib/api/client";
import type { ApiKey } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { apiKeysQueryKey } from "./use-api-keys";

/** One key; revoking asks for confirmation in the row itself. */
export function ApiKeyRow({ apiKey }: { apiKey: ApiKey }) {
  const queryClient = useQueryClient();
  const [confirming, setConfirming] = useState(false);

  const revoke = useMutation({
    mutationFn: () => revokeApiKey(apiKey.id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: apiKeysQueryKey });
      toast.success(`${apiKey.name} revoked`);
    },
    onError: (err) => {
      toast.error(formatErrorForUi(err));
      setConfirming(false);
    },
  });

  return (
    <li className={cn("flex items-center gap-3 py-2.5", apiKey.revoked_at && "opacity-60")}>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-sm font-medium text-foreground">{apiKey.name}</span>
          <Badge variant="outline">{apiKey.scope}</Badge>
          {apiKey.revoked_at ? <Badge variant="destructive">revoked</Badge> : null}
        </div>
        <div className="mt-0.5 flex flex-wrap gap-x-3 text-xs text-muted-foreground">
          <code className="font-mono">{apiKey.prefix}…</code>
          <span>
            Created <RelativeTime date={apiKey.created_at} />
          </span>
          <span>
            {apiKey.last_used_at ? (
              <>
                Used <RelativeTime date={apiKey.last_used_at} />
              </>
            ) : (
              "Never used"
            )}
          </span>
        </div>
      </div>
      {apiKey.revoked_at ? null : confirming ? (
        <div className="flex shrink-0 items-center gap-2">
          <span className="text-xs text-muted-foreground">Reject all requests with this key?</span>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={revoke.isPending}
            onClick={() => setConfirming(false)}
          >
            Cancel
          </Button>
          <Button
            type="button"
            variant="destructive"
            size="sm"
            disabled={revoke.isPending}
            onClick={() => revoke.mutate()}
          >
            {revoke.isPending ? "Revoking…" : "Revoke"}
          </Button>
        </div>
      ) : (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="shrink-0 text-muted-foreground hover:text-status-fail"
          aria-label={`Revoke ${apiKey.name}`}
          onClick={() => setConfirming(true)}
        >
          Revoke
        </Button>
      )}
    </li>
  );
}
