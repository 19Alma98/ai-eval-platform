"use client";

import Link from "next/link";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState, type SubmitEvent } from "react";
import { ArrowLeft } from "lucide-react";
import { toast } from "sonner";
import { useDatasets } from "@/features/datasets/use-datasets";
import { ErrorState } from "@/components/error-state";
import { LoadingBlock } from "@/components/loading-block";
import { RelativeTime } from "@/components/relative-time";
import { StatusBadge } from "@/components/status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { formatErrorForUi } from "@/lib/api/client";
import {
  promoteLiveInteraction,
  rescoreLiveInteraction,
  reviewLiveInteraction,
} from "@/lib/api/live-runs";
import { withProjectQuery } from "@/lib/project-href";
import { useProjectId } from "@/lib/project-store";
import { liveRunQueryKey, useLiveRun } from "./use-live-runs";

export function LiveRunDetail({ interactionId }: { interactionId: string }) {
  const { projectId } = useProjectId();
  const queryClient = useQueryClient();
  const query = useLiveRun(interactionId);
  const datasets = useDatasets(projectId);
  const [note, setNote] = useState("");
  const [promoteOpen, setPromoteOpen] = useState(false);
  const [datasetId, setDatasetId] = useState("");
  const [expectedOverride, setExpectedOverride] = useState("");

  const row = query.data;

  const reviewMutation = useMutation({
    mutationFn: (verdict: "agree" | "disagree") =>
      reviewLiveInteraction(interactionId, {
        verdict,
        note: note.trim() || undefined,
      }),
    onSuccess: async () => {
      toast.success("Review saved");
      await queryClient.invalidateQueries({
        queryKey: liveRunQueryKey(interactionId),
      });
    },
    onError: (err) => toast.error(formatErrorForUi(err)),
  });

  const rescoreMutation = useMutation({
    mutationFn: () => rescoreLiveInteraction(interactionId),
    onSuccess: async () => {
      toast.success("Rescored");
      await queryClient.invalidateQueries({
        queryKey: liveRunQueryKey(interactionId),
      });
    },
    onError: (err) => toast.error(formatErrorForUi(err)),
  });

  const promoteMutation = useMutation({
    mutationFn: () =>
      promoteLiveInteraction(interactionId, {
        dataset_id: datasetId,
        expected_output: expectedOverride.trim() || undefined,
      }),
    onSuccess: (item) => {
      toast.success("Promoted to test set");
      setPromoteOpen(false);
      if (projectId) {
        // leave toast; user can navigate via datasets
        void item;
      }
    },
    onError: (err) => toast.error(formatErrorForUi(err)),
  });

  const docPreview = useMemo(() => {
    if (!row) return [];
    return row.documents.map((d) => ({
      id: String(d.id ?? ""),
      title: typeof d.title === "string" ? d.title : undefined,
      text: typeof d.text === "string" ? d.text : undefined,
    }));
  }, [row]);

  if (query.isLoading) return <LoadingBlock />;
  if (query.isError || !row) {
    return <ErrorState message="Could not load live interaction." />;
  }

  function onPromote(e: SubmitEvent) {
    e.preventDefault();
    if (!datasetId) {
      toast.error("Select a dataset");
      return;
    }
    promoteMutation.mutate();
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <Link
          href={withProjectQuery("/live-runs", projectId)}
          className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-4" />
          Live runs
        </Link>
        <StatusBadge status={row.judge_status} />
        <span className="text-sm text-muted-foreground">
          <RelativeTime date={row.created_at} />
        </span>
        {row.review ? (
          <Badge variant="outline">review: {row.review.verdict}</Badge>
        ) : null}
        <div className="flex-1" />
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={rescoreMutation.isPending}
          onClick={() => rescoreMutation.mutate()}
        >
          Rescore
        </Button>
      </div>

      {row.score_warning ? (
        <p className="rounded-md border border-border bg-surface px-3 py-2 text-sm text-muted-foreground">
          {row.score_warning}
        </p>
      ) : null}
      {row.error_message ? (
        <p className="rounded-md border border-destructive/40 bg-surface px-3 py-2 text-sm text-destructive">
          {row.error_message}
        </p>
      ) : null}

      <section className="space-y-2">
        <h2 className="text-sm font-medium text-foreground">Question</h2>
        <p className="whitespace-pre-wrap text-sm">{row.question}</p>
      </section>
      <section className="space-y-2">
        <h2 className="text-sm font-medium text-foreground">Answer</h2>
        <p className="whitespace-pre-wrap text-sm">{row.answer}</p>
      </section>
      <section className="space-y-2">
        <h2 className="text-sm font-medium text-foreground">Documents</h2>
        {docPreview.length === 0 ? (
          <p className="text-sm text-muted-foreground">No documents</p>
        ) : (
          <ul className="space-y-2">
            {docPreview.map((doc) => (
              <li
                key={doc.id}
                className="rounded-md border border-border bg-surface p-3 text-sm"
              >
                <div className="font-mono text-xs text-muted-foreground">
                  {doc.id}
                  {doc.title ? ` — ${doc.title}` : ""}
                </div>
                {doc.text ? (
                  <p className="mt-1 whitespace-pre-wrap text-foreground">
                    {doc.text}
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="space-y-2">
        <h2 className="text-sm font-medium text-foreground">Judge scores</h2>
        {row.scores.length === 0 ? (
          <p className="text-sm text-muted-foreground">No scores yet</p>
        ) : (
          <div className="grid gap-2 md:grid-cols-2">
            {row.scores.map((score) => (
              <div
                key={score.id}
                className="rounded-md border border-border bg-surface p-3 text-sm"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium">{score.kind}</span>
                  <Badge variant="outline">{score.label ?? "—"}</Badge>
                </div>
                <div className="mt-1 font-mono tabular-nums">
                  {score.score == null ? "—" : score.score.toFixed(3)}
                  {score.threshold != null
                    ? ` (threshold ${score.threshold})`
                    : ""}
                </div>
                {score.explanation ? (
                  <p className="mt-2 text-muted-foreground">
                    {score.explanation}
                  </p>
                ) : null}
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="space-y-3">
        <h2 className="text-sm font-medium text-foreground">Human review</h2>
        <Textarea
          placeholder="Optional note"
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            size="sm"
            disabled={reviewMutation.isPending}
            onClick={() => reviewMutation.mutate("agree")}
          >
            Agree
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={reviewMutation.isPending}
            onClick={() => reviewMutation.mutate("disagree")}
          >
            Disagree
          </Button>

          <Dialog open={promoteOpen} onOpenChange={setPromoteOpen}>
            <DialogTrigger
              render={
                <Button type="button" size="sm" variant="secondary">
                  Promote to TestSet
                </Button>
              }
            />
            <DialogContent>
              <form onSubmit={onPromote}>
                <DialogHeader>
                  <DialogTitle>Promote to test set</DialogTitle>
                  <DialogDescription>
                    Creates a dataset item from this interaction. Expected
                    answer defaults to the production answer.
                  </DialogDescription>
                </DialogHeader>
                <div className="space-y-3 py-3">
                  <label className="block text-sm">
                    Dataset
                    <select
                      className="mt-1 h-9 w-full rounded-md border border-border bg-background px-2 text-sm"
                      value={datasetId}
                      onChange={(e) => setDatasetId(e.target.value)}
                      required
                    >
                      <option value="">Select…</option>
                      {(datasets.data ?? []).map((ds) => (
                        <option key={ds.id} value={ds.id}>
                          {ds.name} v{ds.version}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="block text-sm">
                    Expected output (optional override)
                    <Textarea
                      className="mt-1"
                      value={expectedOverride}
                      onChange={(e) => setExpectedOverride(e.target.value)}
                      placeholder={row.answer}
                    />
                  </label>
                </div>
                <DialogFooter>
                  <Button
                    type="submit"
                    disabled={promoteMutation.isPending}
                  >
                    Promote
                  </Button>
                </DialogFooter>
              </form>
            </DialogContent>
          </Dialog>
        </div>
        {row.review?.note ? (
          <p className="text-sm text-muted-foreground">
            Last note: {row.review.note}
          </p>
        ) : null}
      </section>
    </div>
  );
}
