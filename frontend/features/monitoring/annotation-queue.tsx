"use client";

import Link from "next/link";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, ThumbsDown, ThumbsUp } from "lucide-react";
import { toast } from "sonner";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { LoadingBlock } from "@/components/loading-block";
import { RelativeTime } from "@/components/relative-time";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useDatasets } from "@/features/datasets/use-datasets";
import { LIVE_VERDICT_LABELS, liveVerdict } from "@/features/live-runs/live-verdict";
import { formatErrorForUi } from "@/lib/api/client";
import {
  listLiveInteractions,
  promoteLiveInteraction,
  reviewLiveScore,
} from "@/lib/api/live-runs";
import type { LiveInteraction } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { formatScore } from "@/lib/format";
import { liveRunHref, traceHref } from "@/lib/links";
import { withProjectQuery } from "@/lib/project-href";
import { metricLabel } from "@/lib/metrics-catalog";

const QUEUE_SIZE = 10;
const DATASET_KEY = "aiobs.queue.datasetId";

export function annotationQueueQueryKey(projectId: string) {
  return ["annotation-queue", projectId] as const;
}

function readStoredDataset(projectId: string): string {
  try {
    return localStorage.getItem(`${DATASET_KEY}.${projectId}`) ?? "";
  } catch {
    return "";
  }
}

function QueueItem({
  row,
  projectId,
  datasetId,
}: {
  row: LiveInteraction;
  projectId: string;
  datasetId: string;
}) {
  const queryClient = useQueryClient();
  const [gold, setGold] = useState("");
  const verdict = liveVerdict(row);
  const traceId =
    typeof row.metadata.source_trace_id === "string" ? row.metadata.source_trace_id : null;

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: annotationQueueQueryKey(projectId) });

  const review = useMutation({
    mutationFn: async (v: "agree" | "disagree") => {
      await Promise.all(row.scores.map((s) => reviewLiveScore(s.id, { verdict: v })));
    },
    onSuccess: async () => {
      toast.success("Review saved");
      await invalidate();
    },
    onError: (err) => toast.error(formatErrorForUi(err)),
  });

  const promote = useMutation({
    mutationFn: () =>
      promoteLiveInteraction(row.id, { dataset_id: datasetId, expected_output: gold.trim() }),
    onSuccess: (item) => {
      setGold("");
      toast.success(
        item.dataset_id !== datasetId
          ? "Added to a new version of the test set"
          : "Added to the test set",
      );
    },
    onError: (err) => toast.error(formatErrorForUi(err)),
  });

  return (
    <li className="flex flex-col gap-2 rounded-lg border border-border bg-surface p-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={cn(
            "rounded px-1.5 py-0.5 text-xs font-medium",
            verdict === "failing"
              ? "bg-status-fail-bg text-status-fail"
              : verdict === "passing"
                ? "bg-status-ok-bg text-status-ok"
                : "bg-status-unset-bg text-status-unset",
          )}
        >
          {LIVE_VERDICT_LABELS[verdict]}
        </span>
        <span className="text-xs text-muted-foreground">
          <RelativeTime date={row.created_at} />
        </span>
        <span className="flex-1" />
        {traceId ? (
          <Link href={traceHref(projectId, traceId)} className="text-xs text-primary hover:underline">
            Trace
          </Link>
        ) : null}
        <Link href={liveRunHref(projectId, row.id)} className="text-xs text-primary hover:underline">
          Details
        </Link>
      </div>
      <p className="font-medium text-foreground">{row.question}</p>
      <p className="line-clamp-3 whitespace-pre-wrap text-muted-foreground">{row.answer}</p>
      <div className="flex flex-wrap gap-1">
        {row.scores.map((s) => (
          <span
            key={s.id}
            title={s.explanation ?? undefined}
            className={cn(
              "inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs",
              (s.label ?? "").toUpperCase() === "FAIL"
                ? "bg-status-fail-bg text-status-fail"
                : "bg-surface-2 text-foreground",
            )}
          >
            {metricLabel(s.kind)}
            <span className="font-medium tabular-nums">{formatScore(s.score)}</span>
          </span>
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-2 border-t border-border pt-2">
        <span className="text-xs text-muted-foreground">Is the judge right?</span>
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="h-7"
          disabled={review.isPending}
          onClick={() => review.mutate("agree")}
        >
          <ThumbsUp className="size-3.5" />
          Correct
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="h-7"
          disabled={review.isPending}
          onClick={() => review.mutate("disagree")}
        >
          <ThumbsDown className="size-3.5" />
          Wrong
        </Button>
      </div>
      <div className="flex flex-col gap-1.5 sm:flex-row sm:items-start">
        <Textarea
          value={gold}
          onChange={(e) => setGold(e.target.value)}
          rows={1}
          placeholder="Correct answer, to turn this into a test case…"
          aria-label="Correct answer"
          className="min-h-8 flex-1 bg-background text-sm"
        />
        <Button
          type="button"
          size="sm"
          className="h-8"
          disabled={!datasetId || !gold.trim() || promote.isPending}
          title={datasetId ? undefined : "Choose a test set above"}
          onClick={() => promote.mutate()}
        >
          <Plus className="size-4" />
          {promote.isPending ? "Adding…" : "Add to test set"}
        </Button>
      </div>
    </li>
  );
}

export function AnnotationQueue({ projectId }: { projectId: string }) {
  const datasets = useDatasets(projectId);
  const [datasetId, setDatasetId] = useState(() => readStoredDataset(projectId));
  const query = useQuery({
    queryKey: annotationQueueQueryKey(projectId),
    queryFn: () => listLiveInteractions(projectId, { unreviewedOnly: true, limit: QUEUE_SIZE }),
  });

  function chooseDataset(id: string) {
    setDatasetId(id);
    try {
      localStorage.setItem(`${DATASET_KEY}.${projectId}`, id);
    } catch {
      /* storage unavailable: keep the choice for this visit only */
    }
  }

  const rows = query.data?.items ?? [];

  return (
    <section aria-label="Annotation queue" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-sm font-semibold text-foreground">Annotation queue</h2>
        <span className="text-xs text-muted-foreground">
          The {QUEUE_SIZE} latest judged answers no one has reviewed yet, failures first.
        </span>
        <Link
          href={withProjectQuery("/live-runs", projectId)}
          className="text-xs text-primary hover:underline"
        >
          All live traffic
        </Link>
        <span className="flex-1" />
        <Select value={datasetId} onValueChange={(v) => chooseDataset(v ?? "")}>
          <SelectTrigger className="h-8 w-[220px] text-xs" aria-label="Test set for new cases">
            <SelectValue placeholder="Test set for new cases" />
          </SelectTrigger>
          <SelectContent>
            {(datasets.data ?? []).map((ds) => (
              <SelectItem key={ds.id} value={ds.id} className="text-xs">
                {ds.name} · v{ds.version}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      {query.isLoading ? (
        <LoadingBlock className="min-h-[120px]" />
      ) : query.isError ? (
        <ErrorState
          title="Could not load the queue"
          message={formatErrorForUi(query.error)}
          onRetry={() => void query.refetch()}
        />
      ) : rows.length === 0 ? (
        <EmptyState
          title="Nothing to review"
          description="Every judged answer has been reviewed. New production answers land here once the judge scores them."
        />
      ) : (
        <ul className="flex flex-col gap-2">
          {[...rows]
            .sort(
              (a, b) =>
                Number(liveVerdict(b) === "failing") - Number(liveVerdict(a) === "failing"),
            )
            .map((row) => (
              <QueueItem key={row.id} row={row} projectId={projectId} datasetId={datasetId} />
            ))}
        </ul>
      )}
    </section>
  );
}
