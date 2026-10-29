"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type SubmitEvent } from "react";
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
import { Input } from "@/components/ui/input";
import { LoadingBlock } from "@/components/loading-block";
import { formatErrorForUi } from "@/lib/api/client";
import { getRetention, purgeNow, setRetention } from "@/lib/api/projects";
import type { Project } from "@/lib/api/types";
import { projectsQueryKey } from "@/lib/queries/projects";
import { describePending } from "./retention";

export function RetentionDialog({
  project,
  onOpenChange,
}: {
  project: Project | null;
  onOpenChange: (open: boolean) => void;
}) {
  const queryClient = useQueryClient();
  const projectId = project?.id ?? "";
  const retentionKey = ["project-retention", projectId] as const;
  const query = useQuery({
    queryKey: retentionKey,
    queryFn: () => getRetention(projectId),
    enabled: Boolean(project),
  });
  const [draft, setDraft] = useState<string | null>(null);
  const value = draft ?? (query.data?.retention_days != null ? String(query.data.retention_days) : "");

  async function refresh() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: retentionKey }),
      queryClient.invalidateQueries({ queryKey: projectsQueryKey }),
    ]);
  }

  const save = useMutation({
    mutationFn: () => setRetention(projectId, value.trim() ? Number(value) : null),
    onSuccess: async () => {
      setDraft(null);
      await refresh();
      toast.success("Retention saved");
    },
    onError: (err) => toast.error(formatErrorForUi(err)),
  });
  const purge = useMutation({
    mutationFn: () => purgeNow(projectId),
    onSuccess: async (report) => {
      await refresh();
      toast.success(`Deleted ${describePending(report)}`);
    },
    onError: (err) => toast.error(formatErrorForUi(err)),
  });

  function handleSubmit(e: SubmitEvent) {
    e.preventDefault();
    save.mutate();
  }

  const data = query.data;
  return (
    <Dialog
      open={project != null}
      onOpenChange={(open) => {
        if (!open) setDraft(null);
        onOpenChange(open);
      }}
    >
      <DialogContent className="sm:max-w-md">
        <form onSubmit={handleSubmit}>
          <DialogHeader>
            <DialogTitle>Data retention · {project?.name}</DialogTitle>
            <DialogDescription>
              Production traces, live answers, their scores and alert events older than this
              are deleted daily. Test sets, experiments, and traces used by them are kept.
            </DialogDescription>
          </DialogHeader>
          {query.isLoading || !data ? (
            <LoadingBlock className="min-h-[120px]" />
          ) : (
            <div className="flex flex-col gap-3 py-4">
              <label htmlFor="retention-days" className="text-sm font-medium">
                Keep production data for (days)
              </label>
              <Input
                id="retention-days"
                type="number"
                min={1}
                max={36500}
                value={value}
                onChange={(e) => setDraft(e.target.value)}
                placeholder={
                  data.default_days != null
                    ? `Server default: ${data.default_days}`
                    : "Keep forever"
                }
              />
              <p className="text-xs text-muted-foreground">
                {data.effective_days == null
                  ? "Nothing is deleted: no retention set here or on the server (RETENTION_DAYS)."
                  : `In effect: ${data.effective_days} days${
                      data.retention_days == null ? " (server default)" : ""
                    }. Older than that right now: ${describePending(data.pending)}${
                      data.pending.traces_kept
                        ? ` (${data.pending.traces_kept} old traces kept for evaluation)`
                        : ""
                    }.`}
              </p>
            </div>
          )}
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              disabled={
                purge.isPending || !data?.effective_days || describePending(data.pending) === "nothing"
              }
              onClick={() => purge.mutate()}
            >
              {purge.isPending ? "Deleting…" : "Delete old data now"}
            </Button>
            <Button type="submit" disabled={save.isPending || draft == null}>
              {save.isPending ? "Saving…" : "Save"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
