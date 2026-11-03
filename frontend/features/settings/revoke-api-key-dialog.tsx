"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { revokeApiKey } from "@/lib/api/api-keys";
import { formatErrorForUi } from "@/lib/api/client";
import type { ApiKey } from "@/lib/api/types";
import { apiKeysQueryKey } from "./use-api-keys";

export function RevokeApiKeyDialog({
  apiKey,
  onClose,
}: {
  apiKey: ApiKey | null;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const revoke = useMutation({
    mutationFn: (id: string) => revokeApiKey(id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: apiKeysQueryKey });
      toast.success("Key revoked");
      onClose();
    },
    onError: (err) => toast.error(formatErrorForUi(err)),
  });

  return (
    <Dialog
      open={apiKey != null}
      onOpenChange={(open) => {
        if (!open && !revoke.isPending) onClose();
      }}
    >
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Revoke key</DialogTitle>
          <DialogDescription>
            Requests using{" "}
            <span className="font-medium text-foreground">{apiKey?.name}</span> will be rejected.
            This cannot be undone.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button type="button" variant="outline" disabled={revoke.isPending} onClick={onClose}>
            Cancel
          </Button>
          <Button
            type="button"
            variant="destructive"
            disabled={revoke.isPending || apiKey == null}
            onClick={() => apiKey && revoke.mutate(apiKey.id)}
          >
            {revoke.isPending ? "Revoking…" : "Revoke"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
