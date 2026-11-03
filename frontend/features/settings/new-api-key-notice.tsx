"use client";

import { CopyTechnicalId } from "@/components/copy-technical-id";
import { Button } from "@/components/ui/button";
import type { CreatedApiKey } from "@/lib/api/types";

/** The new key, shown once at the top of the list until dismissed. */
export function NewApiKeyNotice({
  created,
  onDismiss,
}: {
  created: CreatedApiKey;
  onDismiss: () => void;
}) {
  return (
    <div
      role="status"
      className="flex flex-col gap-2 border-t border-l-2 border-border border-l-primary py-3 pl-3"
    >
      <p className="text-sm">
        <span className="font-medium text-foreground">{created.name}</span>{" "}
        <span className="text-muted-foreground">— copy the key now, it is not shown again.</span>
      </p>
      <div className="flex items-center gap-2">
        <code className="min-w-0 flex-1 break-all font-mono text-xs">{created.key}</code>
        <CopyTechnicalId id={created.key} label="Copy API key" />
        <Button type="button" variant="ghost" size="sm" onClick={onDismiss}>
          Done
        </Button>
      </div>
    </div>
  );
}
