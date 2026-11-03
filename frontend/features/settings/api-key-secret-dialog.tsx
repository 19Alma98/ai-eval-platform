"use client";

import { CopyTechnicalId } from "@/components/copy-technical-id";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { CreatedApiKey } from "@/lib/api/types";

/** Shows a newly created key. Closing it drops the key: the server keeps only a hash. */
export function ApiKeySecretDialog({
  created,
  onClose,
}: {
  created: CreatedApiKey | null;
  onClose: () => void;
}) {
  return (
    <Dialog open={created != null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{created?.name}</DialogTitle>
          <DialogDescription>Copy the key now. It is not shown again.</DialogDescription>
        </DialogHeader>
        <div className="flex items-center gap-2 rounded-md border border-border bg-muted/40 px-3 py-2">
          <code className="min-w-0 flex-1 break-all font-mono text-xs">{created?.key}</code>
          {created ? <CopyTechnicalId id={created.key} label="Copy API key" /> : null}
        </div>
        <DialogFooter>
          <Button type="button" onClick={onClose}>
            Done
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
